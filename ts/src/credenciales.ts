/**
 * Dónde viven los tokens de OAuth2, y cómo se rotan sin perder la sesión.
 *
 * EL PELIGRO ESTÁ EN UNA SOLA LÍNEA. El refresh token de Oura es **de un solo
 * uso**: cuando se canjea, Oura lo invalida y entrega uno nuevo. Entre las dos
 * cosas hay una ventana en la que el viejo ya no sirve y el nuevo todavía no
 * está guardado — y si el proceso se cae ahí, la sesión se pierde y hay que
 * volver a autorizar desde el navegador.
 *
 * Por eso `refrescar()` guarda ANTES de devolver, y de forma atómica. No se
 * puede hacer mejor: Oura no ofrece un canje en dos fases. Lo que sí se puede
 * es que la ventana dure lo mínimo y que nunca quede un archivo a medio
 * escribir.
 */

import { chmod, mkdir, readFile, rename, rm, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { dirname, isAbsolute, join, resolve } from "node:path";

import { ErrorOura, Secreto } from "./cliente.js";

export const TOKEN_URL = "https://api.ouraring.com/oauth/token";
export const AUTORIZAR_URL = "https://cloud.ouraring.com/oauth/authorize";
export const REVOCAR_URL = "https://api.ouraring.com/oauth/revoke";

/**
 * La diagonal final NO es un detalle de estilo: el portal de Oura rechaza
 * `…/callback` con `invalid_redirect_uri` y acepta `…/callback/`.
 */
export const REDIRECT_POR_DEFECTO = "http://localhost:9876/callback/";

export const ALCANCES = ["email", "personal", "daily", "heartrate", "workout",
                         "tag", "session", "spo2"] as const;

/**
 * Margen antes de considerar caducado un access token. Uno que expira en tres
 * segundos está, a efectos prácticos, expirado: la petición que se lance con él
 * llegará tarde.
 */
export const MARGEN_CADUCIDAD = 60_000;

/** Dónde vive el archivo. `OURA_CREDENCIALES` lo mueve.
 *
 * SIEMPRE ABSOLUTA. Una ruta relativa pelada —`OURA_CREDENCIALES=cred.json`,
 * que es exactamente lo que alguien escribiría— haría que las credenciales
 * dependieran del directorio desde el que se arrancó el servidor, que en un
 * cliente MCP no es el que uno cree.
 */
export function rutaCredenciales(): string {
  const explicita = (process.env.OURA_CREDENCIALES ?? "").trim();
  if (explicita) {
    const expandida = explicita.replace(/^~/, homedir());
    return isAbsolute(expandida) ? expandida : resolve(expandida);
  }
  const base = process.env.XDG_CONFIG_HOME || join(homedir(), ".config");
  return join(base, "oura-mcp", "credenciales.json");
}

export class Credenciales {
  constructor(
    readonly acceso: Secreto,
    readonly refresco: Secreto | null,
    readonly expiraEn: number,              // epoch en ms
    readonly alcances: readonly string[] = [],
  ) {}

  caducado(margen = MARGEN_CADUCIDAD): boolean {
    return Date.now() + margen >= this.expiraEn;
  }

  comoJson() {
    return {
      acceso: this.acceso.revelar(),
      refresco: this.refresco?.revelar() ?? null,
      expira_en: this.expiraEn,
      alcances: [...this.alcances],
    };
  }

  static desdeJson(d: Record<string, unknown>): Credenciales {
    if (typeof d["acceso"] !== "string") throw new Error("sin `acceso`");
    return new Credenciales(
      new Secreto(d["acceso"]),
      typeof d["refresco"] === "string" ? new Secreto(d["refresco"]) : null,
      Number(d["expira_en"] ?? 0),
      Array.isArray(d["alcances"]) ? (d["alcances"] as string[]) : [],
    );
  }

  /** Ni el acceso ni el refresco salen de aquí. */
  toString(): string {
    const cuando = this.caducado(0)
      ? "caducado"
      : `vigente ${Math.round((this.expiraEn - Date.now()) / 1000)}s`;
    return `<Credenciales ${cuando}, refresco=${this.refresco ? "sí" : "no"}, ` +
           `alcances=${this.alcances.length}>`;
  }

  [Symbol.for("nodejs.util.inspect.custom")](): string {
    return this.toString();
  }
}

/** Persiste las credenciales. Escribe de forma ATÓMICA.
 *
 * Un archivo de credenciales a medio escribir es peor que ninguno: el refresh
 * token viejo ya se consumió, y lo único que podía salvar la sesión era el
 * nuevo.
 */
export async function guardar(cred: Credenciales): Promise<string> {
  const ruta = rutaCredenciales();
  await mkdir(dirname(ruta), { recursive: true, mode: 0o700 });
  const temporal = `${ruta}.${process.pid}.tmp`;
  try {
    await writeFile(temporal, JSON.stringify(cred.comoJson()), { mode: 0o600 });
    await chmod(temporal, 0o600);   // por si el umask se metió
    await rename(temporal, ruta);   // atómico en el mismo sistema de archivos
  } catch (e) {
    await rm(temporal, { force: true });
    throw e;
  }
  return ruta;
}

export async function cargar(): Promise<Credenciales | null> {
  const ruta = rutaCredenciales();
  let crudo: string;
  try {
    crudo = await readFile(ruta, "utf8");
  } catch (e) {
    if ((e as NodeJS.ErrnoException).code === "ENOENT") return null;
    throw new ErrorOura(
      `el archivo de credenciales no se pudo leer. Bórralo y vuelve a autorizar: ${ruta}`);
  }
  try {
    return Credenciales.desdeJson(JSON.parse(crudo) as Record<string, unknown>);
  } catch {
    throw new ErrorOura(
      `el archivo de credenciales está corrupto. Bórralo y vuelve a autorizar: ${ruta}`);
  }
}

export async function olvidar(): Promise<void> {
  await rm(rutaCredenciales(), { force: true });
}

// ── El canje, que es donde se pierde la sesión si se hace mal ─────────────
export async function postear(datos: Record<string, string>): Promise<Record<string, unknown>> {
  let r: Response;
  try {
    r = await fetch(TOKEN_URL, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded", Accept: "application/json" },
      body: new URLSearchParams(datos).toString(),
      signal: AbortSignal.timeout(30_000),
    });
  } catch (e) {
    throw new ErrorOura(`no se pudo alcanzar Oura: ${(e as Error).message}`);
  }
  if (r.ok) return (await r.json()) as Record<string, unknown>;

  // Oura contesta `{"error": …, "error_description": …}`. La descripción es la
  // parte accionable —«Invalid client_id.»— y enterrarla dentro de un JSON
  // crudo obliga a leerlo a quien ya está atorado.
  const texto = await r.text().catch(() => "");
  let detalle = texto.slice(0, 200);
  try {
    const c = JSON.parse(texto) as { error?: string; error_description?: string };
    detalle = c.error_description ?? c.error ?? detalle;
  } catch { /* se queda el crudo */ }
  throw new ErrorOura(`Oura rechazó el canje (${r.status}): ${detalle}`);
}

function deRespuesta(r: Record<string, unknown>, previos: readonly string[] = []): Credenciales {
  if (typeof r["access_token"] !== "string") {
    throw new ErrorOura("Oura respondió sin `access_token`");
  }
  // La pantalla de consentimiento devuelve los alcances CONCEDIDOS, que no
  // siempre son los pedidos. Se guarda lo que Oura dice que dio, no lo que
  // nosotros creímos pedir: el autodiagnóstico se apoya en esto.
  const concedidos = String(r["scope"] ?? "").split(/\s+/).filter(Boolean);
  return new Credenciales(
    new Secreto(r["access_token"]),
    typeof r["refresh_token"] === "string" ? new Secreto(r["refresh_token"]) : null,
    Date.now() + Number(r["expires_in"] ?? 3600) * 1000,
    concedidos.length ? concedidos : [...previos],
  );
}

export async function canjearCodigo(codigo: string, clientId: string, clientSecret: string,
                                    redirectUri = REDIRECT_POR_DEFECTO): Promise<Credenciales> {
  const cred = deRespuesta(await postear({
    grant_type: "authorization_code",
    code: codigo,
    redirect_uri: redirectUri,
    client_id: clientId,
    client_secret: clientSecret,
  }));
  await guardar(cred);
  return cred;
}

/**
 * Renueva el par y lo GUARDA ANTES DE DEVOLVERLO.
 *
 * El orden es todo el punto. En cuanto esta petición sale, el refresh token que
 * teníamos queda muerto. Si el proceso se cayera entre la respuesta y el
 * guardado, la sesión se perdería.
 *
 * Si el canje falla, se relee lo guardado antes de dar la sesión por perdida:
 * dos procesos que refrescan a la vez es un caso real —dos herramientas MCP
 * llamadas en paralelo— y el que pierde la carrera vería un 400 aunque la
 * sesión esté perfectamente viva, ya renovada por el otro.
 */
export async function refrescar(cred: Credenciales, clientId: string,
                                clientSecret: string): Promise<Credenciales> {
  if (!cred.refresco) {
    throw new ErrorOura("no hay refresh token; hay que autorizar de nuevo");
  }
  let r: Record<string, unknown>;
  try {
    r = await postear({
      grant_type: "refresh_token",
      refresh_token: cred.refresco.revelar(),
      client_id: clientId,
      client_secret: clientSecret,
    });
  } catch (e) {
    const otra = await cargar().catch(() => null);
    if (otra?.refresco && !otra.caducado()) return otra;   // alguien más ya refrescó
    throw e;
  }
  const nueva = deRespuesta(r, cred.alcances);
  await guardar(nueva);          // ANTES de devolver. No mover esta línea.
  return nueva;
}
