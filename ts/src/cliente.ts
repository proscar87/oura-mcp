/**
 * Cliente de la API v2 de Oura. Sin dependencias fuera del SDK de MCP.
 *
 * ESTE ARCHIVO ES EL PRODUCTO. Oura nunca devuelve un error cuando no puede
 * darte lo que pediste: devuelve algo distinto, con forma de respuesta
 * correcta. Las cuatro que encontramos midiendo contra la API real, y que aquí
 * se corrigen:
 *
 *   1. `next_token` sin seguir → recibes una fracción. Un día local de
 *      `heartrate` son 1,231 muestras en 2 páginas; quien no pagina recibe
 *      1,000 —el 81%— con aspecto de estar completo.
 *   2. `end_date` es INCONSISTENTE ENTRE COLECCIONES, y `workout` se filtra por
 *      la fecha UTC mientras reporta `day` en hora local. Pedir un solo día
 *      devolvía CERO registros.
 *   3. `latest=true` donde no aplica → Oura devuelve la colección entera.
 *   4. `fields=inventado` → devuelve el registro completo, sin proyectar.
 *
 * Y un tercer final del bucle que casi se escapa: si Oura repite el mismo
 * `next_token`, eso es un ciclo. Sin detectarlo se hacían 50 peticiones
 * idénticas con un aviso que aconsejaba acortar el rango — consejo inútil,
 * porque acortar no arregla que la API se repita.
 */

import {
  ALCANCE_DE, BASE, COLECCIONES, CON_FECHA, CON_ULTIMO, SIN_SANDBOX, forma,
  type Forma,
} from "./colecciones.js";

export const TIEMPO_LIMITE = 30_000;
export const LIMITE_PAGINAS = 50;   // ~50k registros; más que eso es un error de uso
export const REINTENTOS_429 = 2;    // acotado: esto corre dentro de una conversación
export const ESPERA_MAXIMA = 8_000; // ms; ni el `Retry-After` de Oura manda más

/**
 * A partir de cuántos caracteres la respuesta se comenta a sí misma. 50,000 son
 * unos 12,000 tokens: bastante para que importe, poco para que estorbe. Medido:
 * 30 días de `daily_activity` son 252,000, y el 92% es un solo campo.
 */
export const AVISO_TAMANO = 50_000;

/**
 * Días de más que se piden de cada lado antes de recortar. DOS, no uno:
 * `workout` es exclusiva en el extremo Y va desfasada a UTC, y las dos cosas se
 * suman. El desfase horario máximo del mundo es de ±14 h —un día— y la
 * exclusividad cuesta otro. Con dos, cualquier zona horaria queda cubierta.
 */
export const MARGEN_DIAS = 2;

const CLAVES_DIA = ["day", "start_day"] as const;
const CLAVES_HORA = ["timestamp", "start_time", "bedtime_start"] as const;

/** Falla al hablar con Oura. NUNCA lleva el token en el mensaje. */
export class ErrorOura extends Error {
  constructor(mensaje: string) {
    super(mensaje);
    this.name = "ErrorOura";
  }
}

/**
 * Un token que no se imprime por accidente. Hay que pedirlo con `revelar()`.
 *
 * Una cadena con el token adentro sale sola por demasiados lados: un
 * `console.log` de depuración que se quedó, una excepción que arrastra su
 * contexto, un template literal escrito de prisa. Aquí ya costó un token una
 * vez, y la lección no fue «ten más cuidado»: fue que el cuidado no se sostiene
 * a mano.
 */
export class Secreto {
  readonly #valor: string;

  constructor(valor: string) {
    this.#valor = valor;
  }

  revelar(): string {
    return this.#valor;
  }

  get largo(): number {
    return this.#valor.length;
  }

  toString(): string {
    return `<secreto de ${this.#valor.length} caracteres>`;
  }

  toJSON(): string {
    return this.toString();
  }

  // Node imprime esto con console.log y en las trazas.
  [Symbol.for("nodejs.util.inspect.custom")](): string {
    return this.toString();
  }
}

export function enSandbox(): boolean {
  const v = (process.env.OURA_SANDBOX ?? "").trim().toLowerCase();
  return v !== "" && !["0", "no", "false"].includes(v);
}

/**
 * A dónde se pide. Sandbox, override explícito, o Oura de verdad.
 *
 * EL SANDBOX ES OFICIAL, no un truco: está en el OpenAPI de Oura con 34 rutas
 * espejo, y acepta CUALQUIER cadena como `Authorization`. Permite instalar el
 * servidor y verlo funcionar ANTES de pelear con la autenticación — que desde
 * que Oura deprecó los tokens personales en diciembre de 2025 dejó de ser un
 * trámite de un minuto.
 *
 * Lo que el sandbox NO sirve es para medir el comportamiento de la API: es un
 * GENERADOR, no un filtro. Devuelve n-1 registros para cualquier ventana.
 */
export function base(): string {
  const override = (process.env.OURA_API_BASE_URL ?? "").trim();
  if (override) return override.replace(/\/+$/, "");
  if (enSandbox()) return BASE.replace("/v2/usercollection", "/v2/sandbox/usercollection");
  return BASE;
}

/** El día al que pertenece un registro, o null si no se puede saber.
 *
 * `null` significa «no sé», y quien filtra tiene que CONSERVARLO. Descartar lo
 * que no se entiende es la manera más rápida de entregar de menos.
 */
export function diaDe(registro: unknown): string | null {
  if (typeof registro !== "object" || registro === null) return null;
  const r = registro as Record<string, unknown>;
  for (const k of CLAVES_DIA) {
    const v = r[k];
    if (typeof v === "string" && v) return v.slice(0, 10);
  }
  for (const k of CLAVES_HORA) {
    const v = r[k];
    if (typeof v === "string" && v.length >= 10) return v.slice(0, 10);
  }
  return null;
}

/** `AAAA-MM-DD` ± días. Si no parsea, se devuelve tal cual: una fecha mal
 * escrita la rechaza Oura con un 422 que explica qué esperaba, y ese mensaje es
 * más útil que cualquiera que pudiéramos inventar. */
export function correrDias(fecha: string, dias: number): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(fecha);
  if (!m) return fecha;
  const d = new Date(Date.UTC(+m[1]!, +m[2]! - 1, +m[3]!));
  d.setUTCDate(d.getUTCDate() + dias);
  return d.toISOString().slice(0, 10);
}

// ── El token ────────────────────────────────────────────────────────────────
export async function token(): Promise<Secreto> {
  if (enSandbox()) {
    // El sandbox acepta cualquier cadena. Pedir un token aquí sería inventar un
    // requisito que la API no tiene, y con él se pierde justo a quien todavía
    // no tiene cómo conseguirlo.
    return new Secreto("sandbox");
  }
  const ruta = (process.env.OURA_PAT_FILE ?? "").trim();
  if (ruta) {
    const { readFile } = await import("node:fs/promises");
    const { homedir } = await import("node:os");
    let t: string;
    try {
      t = (await readFile(ruta.replace(/^~/, homedir()), "utf8")).trim();
    } catch (e) {
      throw new ErrorOura(`no se pudo leer OURA_PAT_FILE: ${(e as Error).message}`);
    }
    if (!t) throw new ErrorOura(`OURA_PAT_FILE apunta a un archivo vacío: ${ruta}`);
    return new Secreto(t);
  }
  const t = (process.env.OURA_PAT ?? "").trim();
  if (t) return new Secreto(t);
  return tokenDeOauth();
}

async function tokenDeOauth(): Promise<Secreto> {
  const { cargar, refrescar } = await import("./credenciales.js");
  const cred = await cargar();
  if (!cred) {
    // EL MENSAJE IMPORTA. Antes mandaba a la página de tokens personales, y
    // desde diciembre de 2025 esa página ya no deja crear ninguno: quien
    // llegara ahí se quedaba atorado sin saber por qué. Ahora la primera opción
    // es la que funciona, y el sandbox va antes que nada porque permite ver el
    // servidor andar sin conseguir credencial alguna.
    throw new ErrorOura(
      "no hay credenciales. Tres caminos, de menos a más trámite:\n" +
      "  1. OURA_SANDBOX=1 — datos de ejemplo, sin registrarte en nada\n" +
      "  2. oura-mcp --autorizar — OAuth2, una vez, en el navegador\n" +
      "  3. OURA_PAT / OURA_PAT_FILE — sólo si ya tenías un token personal: " +
      "Oura dejó de emitirlos en diciembre de 2025",
    );
  }
  if (!cred.caducado()) return cred.acceso;
  const { credencialesDeApp } = await import("./autorizar.js");
  const [cid, csec] = credencialesDeApp();
  return (await refrescar(cred, cid, csec)).acceso;
}

// ── Una petición, con reintento acotado sólo para el 429 ───────────────────
/** Lo legible del cuerpo de error de Oura, o el crudo recortado.
 *
 * Oura contesta `detail` de dos formas y ninguna se lee en crudo. Una es una
 * cadena; la otra es el arreglo de errores de validación de pydantic, cuyo JSON
 * pasa de los 200 caracteres antes de llegar a lo único que importa —qué campo
 * y por qué—, así que recortarlo dejaba
 * `{"detail":[{"type":"datetime_from_date_parsing","loc":["query","star` y
 * nada más.
 */
export function detalleDe(cuerpo: string): string {
  let d: unknown;
  try {
    d = (JSON.parse(cuerpo) as { detail?: unknown }).detail;
  } catch {
    return "";
  }
  if (typeof d === "string") return ": " + d.slice(0, 200);
  if (Array.isArray(d)) {
    const partes: string[] = [];
    for (const item of d.slice(0, 2)) {
      if (typeof item !== "object" || item === null) continue;
      const i = item as { loc?: unknown[]; msg?: string; input?: unknown };
      const campo = String(i.loc?.[1] ?? "?");
      const recibido = i.input === undefined ? "" : ` (recibido: ${JSON.stringify(i.input)})`;
      partes.push(`${campo}: ${i.msg ?? ""}${recibido}`);
    }
    if (partes.length) return ": " + partes.join("; ").slice(0, 200);
  }
  return ": " + cuerpo.slice(0, 200);
}

/** Cuánto esperar tras un 429: lo que diga `Retry-After`, o backoff. */
export function esperaPedida(retryAfter: string | null, intento: number): number {
  if (retryAfter) {
    const segundos = Number(retryAfter.trim());
    if (Number.isFinite(segundos)) return Math.min(segundos * 1000, ESPERA_MAXIMA);
    const cuando = Date.parse(retryAfter);
    if (Number.isFinite(cuando)) {
      return Math.min(Math.max(cuando - Date.now(), 0), ESPERA_MAXIMA);
    }
  }
  return Math.min(2 ** intento * 1000, ESPERA_MAXIMA);
}

const dormir = (ms: number) => new Promise((r) => setTimeout(r, ms));

/**
 * SÓLO el 429 se reintenta. Un 401 no mejora esperando y un 422 tampoco: lo
 * único que consigue reintentarlos es tardar tres veces más en dar la misma
 * mala noticia.
 *
 * Oura NO manda cabeceras de límite de tasa en las respuestas buenas
 * —verificado el 9-ago-2026— así que un cliente no puede saber qué tan cerca
 * está del tope. Sólo se entera cuando ya se lo negaron, y para entonces puede
 * llevar 30 páginas traídas que se tirarían a la basura.
 */
export async function pedir(url: string, tok: Secreto,
                            reintentos = REINTENTOS_429): Promise<Record<string, unknown>> {
  for (let intento = 0; ; intento++) {
    let r: Response;
    try {
      r = await fetch(url, {
        headers: { Authorization: `Bearer ${tok.revelar()}`, Accept: "application/json" },
        signal: AbortSignal.timeout(TIEMPO_LIMITE),
      });
    } catch (e) {
      throw new ErrorOura(`no se pudo alcanzar Oura: ${(e as Error).message}`);
    }
    if (r.ok) return (await r.json()) as Record<string, unknown>;

    if (r.status === 429 && intento < reintentos) {
      await dormir(esperaPedida(r.headers.get("Retry-After"), intento));
      continue;
    }
    const cuerpo = await r.text().catch(() => "");
    if (r.status === 401) {
      throw new ErrorOura("Oura rechazó el token (401). ¿Expiró la credencial?");
    }
    if (r.status === 429) {
      throw new ErrorOura(
        `Oura está limitando la tasa (429) y siguió limitándola tras ` +
        `${reintentos} reintentos. Espera un poco y acorta el rango.`);
    }
    throw new ErrorOura(`Oura respondió ${r.status}${detalleDe(cuerpo)}`);
  }
}

// ── CSV, avisos y recortes ─────────────────────────────────────────────────
type Registro = Record<string, unknown>;

const celda = (v: unknown): string =>
  v === null || v === undefined ? "" :
  typeof v === "object" ? JSON.stringify(v) : String(v);

/**
 * Los registros como CSV. Un mes de `heartrate` son ~37,000 registros; en JSON
 * eso repite las mismas cuatro claves 37,000 veces.
 *
 * EL ENCABEZADO SALE DE LA UNIÓN DE TODAS LAS CLAVES, no del primer registro.
 * Sacarlo del primero es la forma más fácil de perder datos aquí: basta un
 * registro con un campo extra para que ese campo desaparezca sin dejar rastro.
 */
export function aCsv(datos: Registro[]): { texto: string; columnas: string[]; desiguales: boolean } {
  const claves = new Set<string>();
  for (const r of datos) for (const k of Object.keys(r)) claves.add(k);
  // La fecha primero: es la columna con la que un modelo cruza contra otra
  // fuente, y buscarla a mitad de la tabla es fricción sin motivo.
  const delante = ["day", "timestamp", "start_day", "id"].filter((k) => claves.has(k));
  const columnas = [...delante, ...[...claves].filter((k) => !delante.includes(k)).sort()];
  const desiguales = datos.some((r) => Object.keys(r).length !== claves.size);

  const escapar = (s: string) => (/[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s);
  const filas = [columnas.map(escapar).join(",")];
  for (const r of datos) filas.push(columnas.map((c) => escapar(celda(r[c]))).join(","));
  return { texto: filas.join("\n") + "\n", columnas, desiguales };
}

/** Los campos pedidos que no aparecieron en ningún registro.
 *
 * Oura NO se queja de un nombre de campo que no existe: `fields=no_existe`
 * devuelve el registro COMPLETO —la proyección no ocurre— y `fields=score,malo`
 * aplica el bueno y tira el malo sin decir nada. En los dos casos quien pidió
 * cree haber filtrado y no filtró.
 */
export function camposIgnorados(campos: string[] | undefined, datos: Registro[]): string[] {
  if (!campos?.length || !datos.length) return [];
  const presentes = new Set<string>();
  for (const r of datos) for (const k of Object.keys(r)) presentes.add(k);
  return campos.filter((c) => !presentes.has(c)).sort();
}

/** Si la respuesta es enorme, decirlo y señalar al campo que la infla.
 *
 * Medido: 30 días de `daily_activity` son 252,000 caracteres, y el 92% de cada
 * registro es `met` —una serie de MET por minuto—. Pedir tres columnas baja eso
 * a 5,000: 99% menos. No se recorta nada por cuenta propia —eso sería entregar
 * de menos— pero sí se dice qué pesa y cómo pedir menos.
 */
export function avisoDeTamano(datos: Registro[], campos: string[] | undefined) {
  if (campos?.length || datos.length < 2) return null;
  let total = 0;
  const pesos = new Map<string, number>();
  for (const r of datos) {
    for (const [k, v] of Object.entries(r)) {
      const n = JSON.stringify(v)?.length ?? 0;
      pesos.set(k, (pesos.get(k) ?? 0) + n);
      total += n;
    }
  }
  if (total < AVISO_TAMANO) return null;
  let gordo = "", peso = 0;
  for (const [k, n] of pesos) if (n > peso) { gordo = k; peso = n; }
  const pct = total ? Math.round((peso * 100) / total) : 0;
  return {
    caracteres: total,
    campo_mas_pesado: gordo,
    porcentaje: pct,
    sugerencia: `\`${gordo}\` ocupa el ${pct}% de esta respuesta. Si no lo ` +
      `necesitas, pide sólo las columnas que uses con \`campos\`, o acorta el rango.`,
  };
}

/** Deja sólo los registros cuyo `day` cae en [inicio, fin].
 *
 * Un registro cuyo día NO se puede determinar se conserva. Este filtro existe
 * para corregir un ensanchamiento deliberado, no para decidir qué es un dato
 * válido — descartar lo que no se entiende es la forma más rápida de entregar
 * de menos, que es justo lo que este paquete existe para no hacer.
 */
function recortar(datos: Registro[], inicio: string | undefined, fin: string | undefined,
                  f: Forma): { datos: Registro[]; sobrantes: number } {
  if (f !== "rangoFecha" || !inicio || !fin) return { datos, sobrantes: 0 };
  const piso = inicio.slice(0, 10), techo = fin.slice(0, 10);
  const dentro = datos.filter((r) => {
    const d = diaDe(r);
    return d === null || (d >= piso && d <= techo);
  });
  return { datos: dentro, sobrantes: datos.length - dentro.length };
}

/** Qué se sabe cuando la consulta vuelve sin nada.
 *
 * `n: 0` es la respuesta más común a las preguntas más comunes —«¿cómo dormí
 * ayer?», «¿estoy recuperado?»— y no distingue entre cuatro cosas que llevan a
 * conclusiones opuestas: no llevabas el anillo, no ha sincronizado, pediste una
 * fecha futura, o tu token no tiene ese permiso. Un modelo que reciba `{n: 0}`
 * va a contestar «no dormiste» con toda confianza, y puede estar equivocado.
 *
 * Esto NO adivina cuál es: enumera lo comprobable sin salir a la red.
 */
async function porqueVacio(coleccion: string, inicio?: string, fin?: string) {
  const hoy = new Date().toISOString().slice(0, 10);
  const razones: string[] = [];
  if (inicio && fin) {
    if (inicio.slice(0, 10) > hoy) razones.push("el rango pedido está en el futuro");
    else if (fin.slice(0, 10) >= hoy) {
      razones.push(
        "el rango llega hasta hoy, y los datos de Oura sólo aparecen cuando el " +
        "anillo sincroniza con la app; los del día en curso suelen faltar o " +
        "estar incompletos");
    }
  }
  const alcance = ALCANCE_DE[coleccion];
  const conPat = process.env.OURA_PAT || process.env.OURA_PAT_FILE;
  if (alcance && !enSandbox() && !conPat) {
    try {
      const { cargar } = await import("./credenciales.js");
      const cred = await cargar();
      if (cred && !cred.alcances.includes(alcance)) {
        razones.push(
          `esta colección necesita el alcance \`${alcance}\` y tus credenciales ` +
          `no lo tienen: vuelve a correr \`oura-mcp --autorizar\` y concédelo`);
      }
    } catch { /* si no se pueden leer, no se inventa una razón */ }
  }
  return {
    sin_datos: "la consulta salió bien; Oura no tiene registros en ese rango",
    lo_que_se_sabe: razones.length ? razones : ["nada más que reportar sin salir a la red"],
    no_confundir: "«no hay dato» no es lo mismo que «no dormiste» ni que «no te " +
      "recuperaste». Para saber si el anillo tiene datos cerca, pide un rango más amplio.",
  };
}

// ── `obtener`: el bucle que es el producto ─────────────────────────────────
export interface Opciones {
  inicio?: string;
  fin?: string;
  campos?: string[];
  ultimo?: boolean;
  formato?: "json" | "csv";
  limitePaginas?: number;
}

export async function obtener(coleccion: string, o: Opciones = {}): Promise<Registro> {
  const { inicio, fin, campos, ultimo = false, formato = "json",
          limitePaginas = LIMITE_PAGINAS } = o;
  const f = forma(coleccion);
  const params = new URLSearchParams();

  if (enSandbox() && SIN_SANDBOX.has(coleccion)) {
    // Se atrapa ANTES de la petición. El sandbox contesta 404 a secas, y un
    // «404: Not Found» a quien acaba de instalar le dice que el servidor está
    // roto — cuando lo que pasa es que Oura no pone datos falsos de la única
    // colección con correo, edad, peso y estatura.
    throw new ErrorOura(
      `\`${coleccion}\` no existe en el sandbox de Oura: es la única de las 19 ` +
      `que no sirve, porque es la que devuelve datos personales. Todo lo demás ` +
      `sí funciona aquí. Para ver la tuya de verdad, quita OURA_SANDBOX y corre ` +
      `\`oura-mcp --autorizar\`.`);
  }

  if (ultimo) {
    // Oura NO se queja si se le manda `latest` a una colección que no lo
    // soporta: devuelve la colección entera. Pedir el último registro y recibir
    // diez creyendo que es uno es peor que un error.
    if (!CON_ULTIMO.has(coleccion)) {
      throw new ErrorOura(
        `\`ultimo\` sólo lo respeta Oura en ${[...CON_ULTIMO].sort().join(", ")}; ` +
        `en ${coleccion} lo ignora y devuelve la colección entera`);
    }
    params.set("latest", "true");
  }
  if (campos?.length) params.set("fields", campos.join(","));

  if (CON_FECHA.has(f) && !ultimo) {
    if (!inicio || !fin) throw new ErrorOura(`${coleccion} necesita inicio y fin`);
    if (inicio > fin) {
      // Se atrapa AQUÍ y no en Oura porque el margen cambia las fechas: Oura
      // devolvería un 400 citando dos fechas que quien preguntó nunca escribió.
      throw new ErrorOura(
        `el rango va al revés: inicio (${inicio}) es posterior a fin (${fin})`);
    }
    if (f === "rangoFecha") {
      params.set("start_date", correrDias(inicio, -MARGEN_DIAS));
      params.set("end_date", correrDias(fin, +MARGEN_DIAS));
    } else {
      params.set("start_datetime", inicio);
      params.set("end_datetime", fin);
    }
  }

  const raiz = base();
  const tok = await token();
  let datos: Registro[] = [];
  let paginas = 0, siguiente: string | undefined;
  let truncado: string | undefined, cursor: string | undefined, ciclo: string | undefined;
  const vistos = new Set<string>();

  for (;;) {
    const q = new URLSearchParams(params);
    if (siguiente) q.set("next_token", siguiente);
    const qs = q.toString();
    const cuerpo = await pedir(`${raiz}/${coleccion}${qs ? `?${qs}` : ""}`, tok);
    paginas++;

    // `personal_info` y `ring_configuration` no vienen envueltos en `data`: el
    // cuerpo ENTERO es el registro. Se distingue por la AUSENCIA de la clave.
    // Si `data` viene y no es lista, algo cambió en la API, y envolver el sobre
    // convertiría eso en «un registro» con forma `{data: …}` que se ve legítimo.
    if ("data" in cuerpo) {
      const crudo = cuerpo["data"];
      if (!Array.isArray(crudo)) {
        throw new ErrorOura(
          `Oura devolvió \`data\` como ${crudo === null ? "null" : typeof crudo} y no ` +
          `como lista en ${coleccion}. La forma de la respuesta cambió; no se ` +
          `inventa una interpretación.`);
      }
      datos.push(...(crudo as Registro[]));
    } else if (Object.keys(cuerpo).length) {
      datos.push(cuerpo);
    }

    siguiente = cuerpo["next_token"] as string | undefined;
    if (!siguiente) break;
    if (vistos.has(siguiente)) {
      // UN `next_token` QUE SE REPITE ES UN CICLO. Sin esto se hacían 50
      // peticiones idénticas, se devolvían 50 copias del mismo registro, y el
      // aviso decía «acorta el rango» — consejo inútil, porque acortar no
      // arregla que la API se repita. No es truncamiento y no debe llamarse así.
      ciclo = "Oura repitió el mismo `next_token`: eso es un ciclo, y se paró " +
              "para no pedir lo mismo sin fin. Lo que sigue llega hasta donde se " +
              "pudo avanzar y puede estar incompleto.";
      break;
    }
    vistos.add(siguiente);
    if (paginas >= limitePaginas) {
      truncado = `se detuvo en ${limitePaginas} páginas y Oura ofrecía más; ` +
                 `acorta el rango o sigue desde \`continuar_desde\``;
      cursor = siguiente;
      break;
    }
  }

  const recorte = recortar(datos, inicio, fin, f);
  datos = recorte.datos;

  const salida: Registro = { coleccion, n: datos.length, paginas, datos };
  if (truncado) { salida["truncado"] = truncado; salida["continuar_desde"] = cursor; }
  if (ciclo) salida["ciclo_de_paginacion"] = ciclo;
  if (formato === "csv") {
    const { texto, columnas, desiguales } = aCsv(datos);
    salida["datos"] = texto;
    salida["formato"] = "csv";
    salida["columnas"] = columnas;
    if (desiguales) {
      salida["columnas_desiguales"] =
        "no todos los registros traen las mismas claves; una celda vacía puede " +
        "ser campo ausente o valor nulo";
    }
  }
  const ignorados = camposIgnorados(campos, datos);
  if (ignorados.length) salida["campos_ignorados"] = ignorados;
  const aviso = avisoDeTamano(datos, campos);
  if (aviso) salida["respuesta_grande"] = aviso;
  if (recorte.sobrantes) salida["descartados_fuera_de_rango"] = recorte.sobrantes;
  if (!datos.length) salida["vacio"] = await porqueVacio(coleccion, inicio, fin);
  return salida;
}

export { COLECCIONES, CON_FECHA, forma };
