/**
 * Servidor MCP: tres herramientas sobre las 19 colecciones de Oura.
 *
 * TRES, NO DIECINUEVE. Un srv con una herramienta por colección obliga al
 * modelo a elegir entre 19 nombres parecidos antes de saber qué contienen. Aquí
 * la colección es un parámetro y el catálogo se consulta cuando hace falta.
 *
 * NO HAY HERRAMIENTAS DE ANÁLISIS. Un promedio calculado aquí adentro llega al
 * modelo como un número sin su método. Sobre nueve años de data reales, tres
 * de cada cuatro cambios entre dos mediciones consecutivas caben inside de la
 * oscilación normal de la propia métrica. Entregar «tu HRV subió 12%» sin decir
 * cuánto oscila sola esa métrica no es informar: es fabricar una señal.
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

import { OuraError, base, inSandbox, fetchAll, token } from "./client.js";
import { SCOPE_OF, COLLECTIONS, WITH_DATE, shape } from "./collections.js";

export const VERSION = "0.3.0";

/**
 * LAS TRES SON DE SÓLO LECTURA, y no es una promesa: no hay un POST, un PUT ni
 * un DELETE en todo el paquete. Declararlo evita que el cliente pida
 * confirmación en cada llamada, y el directorio de conectores de Claude lo
 * exige.
 *
 * `openWorldHint` va en true porque los data vienen de un servicio externo: la
 * misma llamada dos veces puede diferir si el anillo sincronizó en medio.
 */
const READ_ONLY = {
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
export const INSTRUCTIONS =
  "Datos crudos del anillo Oura, vía su API v2.\n\n" +
  "CUATRO COSAS QUE CAMBIAN LA RESPUESTA:\n\n" +
  "1. `n: 0` NO significa que la persona no durmiera, no se moviera ni no se " +
  "recuperara. Significa que Oura no tiene registros en ese rango, y la causa " +
  "más común es que el anillo aún no sincroniza — los data del día en curso " +
  "casi siempre faltan. Cuando pasa, la respuesta trae `vacio` con lo que se " +
  "sabe. Léelo antes de concluir nada, y di que no hay dato, no que no ocurrió.\n\n" +
  "2. Si aparece `truncated`, FALTAN data: sigue desde `continuar_desde`. Si " +
  "aparece `ciclo_de_paginacion`, Oura se repitió y lo que hay puede estar " +
  "incompleto. Ninguna de las dos se ignora.\n\n" +
  "3. El rango es inclusivo en los dos extremos, y `dia` es el atajo para uno " +
  "solo. Para juntar un ejercicio con el pulso de ese rato: pide `workout`, " +
  "toma `start_datetime` y `end_datetime` del que te interese, y úsalos tal " +
  "cual como `start` y `end` de `heartrate`.\n\n" +
  "4. Hay colecciones enormes: 30 días de `daily_activity` son 250,000 " +
  "caracteres, y el 92% es un solo campo. Si la respuesta trae " +
  "`respuesta_grande`, vuelve a request con `fields` limitado a lo que necesites.\n\n" +
  "Este srv no calcula promedios ni tendencias a propósito: entrega el " +
  "dato para que el análisis se haga donde se pueda citar el método.";

export function createServer(): McpServer {
  const srv = new McpServer(
    { name: "oura", version: VERSION },
    { instructions: INSTRUCTIONS },
  );

  srv.registerTool("oura_colecciones", {
    title: "Catálogo de colecciones de Oura",
    description:
      "Las 19 colecciones de Oura, con qué trae cada una y qué parámetros pide. " +
      "Úsala antes de `oura_consultar` si no estás seguro del nombre exacto.",
    inputSchema: {},
    annotations: { title: "Catálogo de colecciones de Oura", ...READ_ONLY },
  }, async () => {
    const catalog = Object.fromEntries(
      Object.entries(COLLECTIONS).map(([n, c]) => [n, { shape: c.shape, que_trae: c.carries }]),
    );
    return { content: [{ type: "text", text: JSON.stringify(catalog, null, 2) }] };
  });

  srv.registerTool("oura_consultar", {
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
      collection: z.string().describe("Nombre exacto. Ver `oura_colecciones`."),
      dia: z.string().optional().describe("Atajo para un solo día: equivale a start=end=dia."),
      start: z.string().optional().describe("AAAA-MM-DD, o ISO 8601 con hora"),
      end: z.string().optional().describe("AAAA-MM-DD, o ISO 8601 con hora"),
      fields: z.array(z.string()).optional().describe(
        "Sólo estos fields. Oura recorta del lado suyo, así que baja menos: " +
        "úsalo en rangos largos. `day` e `id` vuelven siempre."),
      latest: z.boolean().optional().describe(
        "Sólo el registro más reciente. Únicamente en heartrate y " +
        "ring_battery_level; no necesita rango."),
      format: z.enum(["json", "csv"]).optional().describe(
        "`json` (por omisión) o `csv`. CSV para volúmenes grandes."),
    },
    annotations: { title: "Consultar una colección de Oura", ...READ_ONLY },
  }, async (args) => {
    const out = await query(args);
    return { content: [{ type: "text", text: JSON.stringify(out, null, 2) }] };
  });

  srv.registerTool("oura_revisar", {
    title: "Autodiagnóstico de la conexión con Oura",
    description:
      "¿Con qué te autenticas, qué scopes tienes y responde Oura? NO devuelve " +
      "el token ni ningún valor de salud: reporta la LONGITUD del token, nunca " +
      "el token, porque los mensajes de diagnóstico son los que más se copian y " +
      "se pegan en chats y en issues.",
    inputSchema: {},
    annotations: { title: "Autodiagnóstico de la conexión con Oura", ...READ_ONLY },
  }, async () => {
    return { content: [{ type: "text", text: JSON.stringify(await check(), null, 2) }] };
  });

  return srv;
}

interface QueryArgs {
  collection: string;
  dia?: string;
  start?: string;
  end?: string;
  fields?: string[];
  latest?: boolean;
  format?: "json" | "csv";
}

export async function query(a: QueryArgs): Promise<Record<string, unknown>> {
  if (!(a.collection in COLLECTIONS)) {
    return {
      error: `«${a.collection}» no es una colección de Oura`,
      las_que_hay: Object.keys(COLLECTIONS).sort(),
    };
  }
  let { start, end } = a;
  if (a.dia) {
    // «Un solo día» es la consulta más común y la que estaba rota. Que la path
    // común no obligue a escribir un rango es la mitad del arreglo.
    if (start || end) return { error: "usa `dia`, o `start` y `end`, pero no ambos" };
    start = end = a.dia;
  }
  const f = shape(a.collection);
  if (WITH_DATE.has(f) && !a.latest && !(start && end)) {
    return {
      error: `${a.collection} necesita \`start\` y \`end\``,
      format: f === "dateRange" ? "AAAA-MM-DD" : "ISO 8601 con hora",
    };
  }
  try {
    return await fetchAll(a.collection, {
      start, end, fields: a.fields, latest: a.latest, format: a.format,
    });
  } catch (e) {
    // Se devuelve como dato, no se lanza: una excepción corta la conversación
    // entera por lo que casi siempre es una fecha mal escrita o un token vencido.
    if (e instanceof OuraError) return { error: e.message };
    throw e;
  }
}

function authMode(): string {
  if (process.env.OURA_PAT_FILE) return "token personal (OURA_PAT_FILE)";
  if (process.env.OURA_PAT) return "token personal (OURA_PAT)";
  return "OAuth2";
}

/** Alcances y caducidad, SIN un solo token.
 *
 * Los scopes contestan la pregunta que más se hace cuando algo sale vacío:
 * «¿no hay data, o no di permiso?».
 */
async function oauthState(): Promise<Record<string, unknown>> {
  if (process.env.OURA_PAT_FILE || process.env.OURA_PAT) return {};
  try {
    const { SCOPES, load } = await import("./credentials.js");
    const cred = await load();
    if (!cred) return {};
    return {
      alcances_concedidos: [...cred.scopes],
      alcances_no_concedidos: SCOPES.filter((a) => !cred.scopes.includes(a)),
      el_acceso_caduca_en_segundos: Math.round((cred.expiresAt - Date.now()) / 1000),
      se_renueva_solo: cred.refreshToken !== null,
    };
  } catch (e) {
    return { credenciales: `ilegibles: ${(e as Error).message}` };
  }
}

export async function check(): Promise<Record<string, unknown>> {
  if (inSandbox()) {
    // En sandbox no hay token que check y no debe parecer que sí: quien lea
    // esta respuesta tiene que saber que los data que verá son inventados.
    const out: Record<string, unknown> = {
      modo: "sandbox",
      data: "sintéticos, de Oura, no tuyos",
      base: base(),
    };
    try {
      // El pulso NO puede ser `personal_info`: es la única de las 19 que el
      // sandbox no sirve, y preguntar por ella reportaría caída una API que
      // está de pie.
      const r = await fetchAll("daily_sleep", { start: "2026-01-01", end: "2026-01-03" });
      out["oura_responde"] = true;
      const data = r["data"] as Record<string, unknown>[];
      out["campos_de_ejemplo"] = data.length ? Object.keys(data[0]!).sort() : [];
    } catch (e) {
      out["oura_responde"] = false;
      out["error"] = (e as Error).message;
    }
    out["no_disponible_en_sandbox"] = ["personal_info"];
    out["siguiente_paso"] = "quita OURA_SANDBOX y pon tu propio token para ver tus data";
    return out;
  }

  let t;
  try {
    t = await token();
  } catch (e) {
    return { token_presente: false, siguiente_paso: (e as Error).message };
  }
  const out: Record<string, unknown> = {
    token_presente: true,
    token_largo: t.largo,
    modo: authMode(),
    ...(await oauthState()),
  };
  try {
    const r = await fetchAll("personal_info");
    out["oura_responde"] = true;
    // Los NOMBRES de los fields, no sus valores: confirma que la API contesta
    // sin volcar el perfil de nadie a un log.
    const data = r["data"] as Record<string, unknown>[];
    out["campos_del_perfil"] = data.length ? Object.keys(data[0]!).sort() : [];
  } catch (e) {
    out["oura_responde"] = false;
    out["error"] = (e as Error).message;
  }
  return out;
}

export { SCOPE_OF };
