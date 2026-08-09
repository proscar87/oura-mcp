/**
 * Servidor MCP: tres herramientas sobre las 19 colecciones de Oura.
 *
 * TRES, NO DIECINUEVE. Un servidor con una herramienta por colección obliga al
 * modelo a elegir entre 19 nombres parecidos antes de saber qué contienen. Aquí
 * la colección es un parámetro y el catálogo se consulta cuando hace falta.
 *
 * NO HAY HERRAMIENTAS DE ANÁLISIS. Un promedio calculado aquí adentro llega al
 * modelo como un número sin su método. Sobre nueve años de datos reales, tres
 * de cada cuatro cambios entre dos mediciones consecutivas caben dentro de la
 * oscilación normal de la propia métrica. Entregar «tu HRV subió 12%» sin decir
 * cuánto oscila sola esa métrica no es informar: es fabricar una señal.
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

import { ErrorOura, base, enSandbox, obtener, token } from "./cliente.js";
import { ALCANCE_DE, COLECCIONES, CON_FECHA, forma } from "./colecciones.js";

export const VERSION = "0.3.0";

/**
 * LAS TRES SON DE SÓLO LECTURA, y no es una promesa: no hay un POST, un PUT ni
 * un DELETE en todo el paquete. Declararlo evita que el cliente pida
 * confirmación en cada llamada, y el directorio de conectores de Claude lo
 * exige.
 *
 * `openWorldHint` va en true porque los datos vienen de un servicio externo: la
 * misma llamada dos veces puede diferir si el anillo sincronizó en medio.
 */
const SOLO_LECTURA = {
  readOnlyHint: true,
  destructiveHint: false,
  idempotentHint: true,
  openWorldHint: true,
} as const;

/**
 * LO QUE UN MODELO NO PUEDE ADIVINAR. Se comprobó simulando las preguntas que
 * un usuario hace de verdad y viendo qué le faltaba saber para contestarlas sin
 * inventar. Estas instrucciones viajan en cada sesión, así que sólo va lo que
 * cambia una respuesta.
 */
export const INSTRUCCIONES =
  "Datos crudos del anillo Oura, vía su API v2.\n\n" +
  "CUATRO COSAS QUE CAMBIAN LA RESPUESTA:\n\n" +
  "1. `n: 0` NO significa que la persona no durmiera, no se moviera ni no se " +
  "recuperara. Significa que Oura no tiene registros en ese rango, y la causa " +
  "más común es que el anillo aún no sincroniza — los datos del día en curso " +
  "casi siempre faltan. Cuando pasa, la respuesta trae `vacio` con lo que se " +
  "sabe. Léelo antes de concluir nada, y di que no hay dato, no que no ocurrió.\n\n" +
  "2. Si aparece `truncado`, FALTAN datos: sigue desde `continuar_desde`. Si " +
  "aparece `ciclo_de_paginacion`, Oura se repitió y lo que hay puede estar " +
  "incompleto. Ninguna de las dos se ignora.\n\n" +
  "3. El rango es inclusivo en los dos extremos, y `dia` es el atajo para uno " +
  "solo. Para juntar un ejercicio con el pulso de ese rato: pide `workout`, " +
  "toma `start_datetime` y `end_datetime` del que te interese, y úsalos tal " +
  "cual como `inicio` y `fin` de `heartrate`.\n\n" +
  "4. Hay colecciones enormes: 30 días de `daily_activity` son 250,000 " +
  "caracteres, y el 92% es un solo campo. Si la respuesta trae " +
  "`respuesta_grande`, vuelve a pedir con `campos` limitado a lo que necesites.\n\n" +
  "Este servidor no calcula promedios ni tendencias a propósito: entrega el " +
  "dato para que el análisis se haga donde se pueda citar el método.";

export function crearServidor(): McpServer {
  const servidor = new McpServer(
    { name: "oura", version: VERSION },
    { instructions: INSTRUCCIONES },
  );

  servidor.registerTool("oura_colecciones", {
    title: "Catálogo de colecciones de Oura",
    description:
      "Las 19 colecciones de Oura, con qué trae cada una y qué parámetros pide. " +
      "Úsala antes de `oura_consultar` si no estás seguro del nombre exacto.",
    inputSchema: {},
    annotations: { title: "Catálogo de colecciones de Oura", ...SOLO_LECTURA },
  }, async () => {
    const catalogo = Object.fromEntries(
      Object.entries(COLECCIONES).map(([n, c]) => [n, { forma: c.forma, que_trae: c.queTrae }]),
    );
    return { content: [{ type: "text", text: JSON.stringify(catalogo, null, 2) }] };
  });

  servidor.registerTool("oura_consultar", {
    title: "Consultar una colección de Oura",
    description:
      "Trae una colección de Oura COMPLETA en el rango pedido, siguiendo la " +
      "paginación hasta el final: Oura entrega `next_token` y quien no lo " +
      "persigue recibe la primera página sin que nada se lo diga. Un día local " +
      "de `heartrate` son 1,231 muestras en 2 páginas.\n\n" +
      "El rango es INCLUSIVO en los dos extremos. Oura no se comporta así —unas " +
      "colecciones excluyen el último día y otras no, y `workout` va desfasada a " +
      "UTC— pero eso se corrige aquí.",
    inputSchema: {
      coleccion: z.string().describe("Nombre exacto. Ver `oura_colecciones`."),
      dia: z.string().optional().describe("Atajo para un solo día: equivale a inicio=fin=dia."),
      inicio: z.string().optional().describe("AAAA-MM-DD, o ISO 8601 con hora"),
      fin: z.string().optional().describe("AAAA-MM-DD, o ISO 8601 con hora"),
      campos: z.array(z.string()).optional().describe(
        "Sólo estos campos. Oura recorta del lado suyo, así que baja menos: " +
        "úsalo en rangos largos. `day` e `id` vuelven siempre."),
      ultimo: z.boolean().optional().describe(
        "Sólo el registro más reciente. Únicamente en heartrate y " +
        "ring_battery_level; no necesita rango."),
      formato: z.enum(["json", "csv"]).optional().describe(
        "`json` (por omisión) o `csv`. CSV para volúmenes grandes."),
    },
    annotations: { title: "Consultar una colección de Oura", ...SOLO_LECTURA },
  }, async (args) => {
    const salida = await consultar(args);
    return { content: [{ type: "text", text: JSON.stringify(salida, null, 2) }] };
  });

  servidor.registerTool("oura_revisar", {
    title: "Autodiagnóstico de la conexión con Oura",
    description:
      "¿Con qué te autenticas, qué alcances tienes y responde Oura? NO devuelve " +
      "el token ni ningún valor de salud: reporta la LONGITUD del token, nunca " +
      "el token, porque los mensajes de diagnóstico son los que más se copian y " +
      "se pegan en chats y en issues.",
    inputSchema: {},
    annotations: { title: "Autodiagnóstico de la conexión con Oura", ...SOLO_LECTURA },
  }, async () => {
    return { content: [{ type: "text", text: JSON.stringify(await revisar(), null, 2) }] };
  });

  return servidor;
}

interface ArgsConsultar {
  coleccion: string;
  dia?: string;
  inicio?: string;
  fin?: string;
  campos?: string[];
  ultimo?: boolean;
  formato?: "json" | "csv";
}

export async function consultar(a: ArgsConsultar): Promise<Record<string, unknown>> {
  if (!(a.coleccion in COLECCIONES)) {
    return {
      error: `«${a.coleccion}» no es una colección de Oura`,
      las_que_hay: Object.keys(COLECCIONES).sort(),
    };
  }
  let { inicio, fin } = a;
  if (a.dia) {
    // «Un solo día» es la consulta más común y la que estaba rota. Que la ruta
    // común no obligue a escribir un rango es la mitad del arreglo.
    if (inicio || fin) return { error: "usa `dia`, o `inicio` y `fin`, pero no ambos" };
    inicio = fin = a.dia;
  }
  const f = forma(a.coleccion);
  if (CON_FECHA.has(f) && !a.ultimo && !(inicio && fin)) {
    return {
      error: `${a.coleccion} necesita \`inicio\` y \`fin\``,
      formato: f === "rangoFecha" ? "AAAA-MM-DD" : "ISO 8601 con hora",
    };
  }
  try {
    return await obtener(a.coleccion, {
      inicio, fin, campos: a.campos, ultimo: a.ultimo, formato: a.formato,
    });
  } catch (e) {
    // Se devuelve como dato, no se lanza: una excepción corta la conversación
    // entera por lo que casi siempre es una fecha mal escrita o un token vencido.
    if (e instanceof ErrorOura) return { error: e.message };
    throw e;
  }
}

function modoDeAutenticacion(): string {
  if (process.env.OURA_PAT_FILE) return "token personal (OURA_PAT_FILE)";
  if (process.env.OURA_PAT) return "token personal (OURA_PAT)";
  return "OAuth2";
}

/** Alcances y caducidad, SIN un solo token.
 *
 * Los alcances contestan la pregunta que más se hace cuando algo sale vacío:
 * «¿no hay datos, o no di permiso?».
 */
async function estadoDeOauth(): Promise<Record<string, unknown>> {
  if (process.env.OURA_PAT_FILE || process.env.OURA_PAT) return {};
  try {
    const { ALCANCES, cargar } = await import("./credenciales.js");
    const cred = await cargar();
    if (!cred) return {};
    return {
      alcances_concedidos: [...cred.alcances],
      alcances_no_concedidos: ALCANCES.filter((a) => !cred.alcances.includes(a)),
      el_acceso_caduca_en_segundos: Math.round((cred.expiraEn - Date.now()) / 1000),
      se_renueva_solo: cred.refresco !== null,
    };
  } catch (e) {
    return { credenciales: `ilegibles: ${(e as Error).message}` };
  }
}

export async function revisar(): Promise<Record<string, unknown>> {
  if (enSandbox()) {
    // En sandbox no hay token que revisar y no debe parecer que sí: quien lea
    // esta respuesta tiene que saber que los datos que verá son inventados.
    const salida: Record<string, unknown> = {
      modo: "sandbox",
      datos: "sintéticos, de Oura, no tuyos",
      base: base(),
    };
    try {
      // El pulso NO puede ser `personal_info`: es la única de las 19 que el
      // sandbox no sirve, y preguntar por ella reportaría caída una API que
      // está de pie.
      const r = await obtener("daily_sleep", { inicio: "2026-01-01", fin: "2026-01-03" });
      salida["oura_responde"] = true;
      const datos = r["datos"] as Record<string, unknown>[];
      salida["campos_de_ejemplo"] = datos.length ? Object.keys(datos[0]!).sort() : [];
    } catch (e) {
      salida["oura_responde"] = false;
      salida["error"] = (e as Error).message;
    }
    salida["no_disponible_en_sandbox"] = ["personal_info"];
    salida["siguiente_paso"] = "quita OURA_SANDBOX y pon tu propio token para ver tus datos";
    return salida;
  }

  let t;
  try {
    t = await token();
  } catch (e) {
    return { token_presente: false, siguiente_paso: (e as Error).message };
  }
  const salida: Record<string, unknown> = {
    token_presente: true,
    token_largo: t.largo,
    modo: modoDeAutenticacion(),
    ...(await estadoDeOauth()),
  };
  try {
    const r = await obtener("personal_info");
    salida["oura_responde"] = true;
    // Los NOMBRES de los campos, no sus valores: confirma que la API contesta
    // sin volcar el perfil de nadie a un log.
    const datos = r["datos"] as Record<string, unknown>[];
    salida["campos_del_perfil"] = datos.length ? Object.keys(datos[0]!).sort() : [];
  } catch (e) {
    salida["oura_responde"] = false;
    salida["error"] = (e as Error).message;
  }
  return salida;
}

export { ALCANCE_DE };
