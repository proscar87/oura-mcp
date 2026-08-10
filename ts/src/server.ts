/**
 * Servidor MCP: tres herramientas sobre las 19 colecciones de Oura.
 *
 * THREE, NOT NINETEEN. A server with one tool per collection forces the model
 * to choose among 19 similar names before knowing what any of them contain. Here
 * the collection is a parameter and the catalog is consulted when needed.
 *
 * THERE ARE NO ANALYSIS TOOLS. An average computed in here reaches the model
 * as a number without its method. Across nine years of real data, three out of
 * four changes between consecutive measurements fall within the metric's own
 * normal oscillation. Handing over "your HRV is up 12%" without saying how much
 * that metric swings on its own isn't informing: it's manufacturing a signal.
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

import { OuraError, base, inSandbox, fetchAll, token } from "./client.js";
import { SCOPE_OF, COLLECTIONS, WITH_DATE, shape } from "./collections.js";

export const VERSION = "0.3.0";

/**
 * ALL THREE ARE READ-ONLY, and that isn't a promise: there is no POST, PUT or
 * DELETE anywhere in the package. Declaring it stops the client asking for
 * confirmation on every call, and Claude's connectors directory requires it.
 *
 * `openWorldHint` is true because the data comes from an external service: the
 * same call twice can differ if the ring synced in between.
 */
const READ_ONLY = {
  readOnlyHint: true,
  destructiveHint: false,
  idempotentHint: true,
  openWorldHint: true,
} as const;

/**
 * WHAT A MODEL CANNOT GUESS. Verified by simulating the questions a user
 * actually asks and seeing what they were missing to answer without inventing.
 * These instructions travel in every session, so only what changes an answer
 * goes in.
 */
export const INSTRUCTIONS =
  "Raw data from the Oura ring, via its v2 API.\n\n" +
  "FOUR THINGS THAT CHANGE THE ANSWER:\n\n" +
  "1. `n: 0` does NOT mean the person didn't sleep, didn't move or didn't " +
  "recover. It means Oura has no records in that range, and the most common " +
  "cause is that the ring hasn't synced yet — the current day is almost always " +
  "missing. When that happens the response carries `empty` with what is known. " +
  "Read it before concluding anything, and say there is no data, not that it " +
  "didn't happen.\n\n" +
  "2. If `truncated` appears, data is MISSING: continue from `continue_from`. " +
  "If `pagination_cycle` appears, Oura repeated itself and what you have may " +
  "be incomplete. Neither one gets ignored.\n\n" +
  "3. The range is inclusive on both ends, and `day` is the shorthand for a " +
  "single one. To join a workout with the heart rate during it: request " +
  "`workout`, take `start_datetime` and `end_datetime` from the one you care " +
  "about, and use them verbatim as `start` and `end` of `heartrate`.\n\n" +
  "4. Some collections are enormous: 30 days of `daily_activity` is 250,000 " +
  "characters, and 92% of it is a single field. If the response carries " +
  "`large_response`, ask again with `fields` limited to what you need.\n\n" +
  "This server deliberately computes no averages and no trends: it hands over " +
  "the data so the analysis happens where the method can be cited.";

export function createServer(): McpServer {
  const srv = new McpServer(
    { name: "oura", version: VERSION },
    { instructions: INSTRUCTIONS },
  );

  srv.registerTool("oura_colecciones", {
    title: "Oura collection catalog",
    description:
      "The 19 Oura collections, what each one carries and which parameters it " +
      "takes. Use it before `oura_query` if you are unsure of the exact name.",
    inputSchema: {},
    annotations: { title: "Oura collection catalog", ...READ_ONLY },
  }, async () => {
    const catalog = Object.fromEntries(
      Object.entries(COLLECTIONS).map(([n, c]) => [n, { shape: c.shape, que_trae: c.carries }]),
    );
    return { content: [{ type: "text", text: JSON.stringify(catalog, null, 2) }] };
  });

  srv.registerTool("oura_consultar", {
    title: "Query an Oura collection",
    description:
      "Fetches a COMPLETE Oura collection over the requested range, following " +
      "pagination to the end: Oura returns `next_token` and whoever doesn't " +
      "chase it receives the first page with nothing saying so. One local day " +
      "of `heartrate` is 1,231 samples across 2 pages.\n\n" +
      "The range is INCLUSIVE on both ends. Oura does not behave that way — some " +
      "collections exclude the last day and others don't, and `workout` is " +
      "skewed to UTC — but that is corrected here.",
    inputSchema: {
      collection: z.string().describe("Nombre exacto. Ver `oura_colecciones`."),
      day: z.string().optional().describe("Shorthand for a single day: equivalent to start=end=day."),
      start: z.string().optional().describe("AAAA-MM-DD, o ISO 8601 con hora"),
      end: z.string().optional().describe("AAAA-MM-DD, o ISO 8601 con hora"),
      fields: z.array(z.string()).optional().describe(
        "Only these fields. Oura trims on its side, so less comes down: " +
        "use it on long ranges. `day` and `id` always come back."),
      latest: z.boolean().optional().describe(
        "Only the most recent record. heartrate and ring_battery_level only; " +
        "it needs no range."),
      format: z.enum(["json", "csv"]).optional().describe(
        "`json` (default) or `csv`. CSV for large volumes."),
    },
    annotations: { title: "Query an Oura collection", ...READ_ONLY },
  }, async (args) => {
    const out = await query(args);
    return { content: [{ type: "text", text: JSON.stringify(out, null, 2) }] };
  });

  srv.registerTool("oura_revisar", {
    title: "Self-check of the Oura connection",
    description:
      "Which credential are you using, which scopes do you have, and does Oura " +
      "respond? Returns neither the token nor any health value: it reports the " +
      "token's LENGTH, never the token, because diagnostic messages are the " +
      "ones most often copied into chats and issues.",
    inputSchema: {},
    annotations: { title: "Self-check of the Oura connection", ...READ_ONLY },
  }, async () => {
    return { content: [{ type: "text", text: JSON.stringify(await check(), null, 2) }] };
  });

  return srv;
}

interface QueryArgs {
  collection: string;
  day?: string;
  start?: string;
  end?: string;
  fields?: string[];
  latest?: boolean;
  format?: "json" | "csv";
}

export async function query(a: QueryArgs): Promise<Record<string, unknown>> {
  if (!(a.collection in COLLECTIONS)) {
    return {
      error: `«${a.collection}» is not an Oura collection`,
      las_que_hay: Object.keys(COLLECTIONS).sort(),
    };
  }
  let { start, end } = a;
  if (a.day) {
    // "A single day" is the most common query and the one that was broken.
    // Making the common path not require a range is half the fix.
    if (start || end) return { error: "use `day`, or `start` and `end`, but not both" };
    start = end = a.day;
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
    // Returned as data, not thrown: an exception cuts the whole conversation
    // short over what is almost always a malformed date or an expired token.
    if (e instanceof OuraError) return { error: e.message };
    throw e;
  }
}

function authMode(): string {
  if (process.env.OURA_PAT_FILE) return "personal token (OURA_PAT_FILE)";
  if (process.env.OURA_PAT) return "personal token (OURA_PAT)";
  return "OAuth2";
}

/** Alcances y caducidad, SIN un solo token.
 *
 * The scopes answer the question people ask most when something comes back
 * empty: "is there no data, or did I not grant permission?"
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
    return { credenciales: `unreadable: ${(e as Error).message}` };
  }
}

export async function check(): Promise<Record<string, unknown>> {
  if (inSandbox()) {
    // In sandbox there is no token to check and it mustn't look like there is:
    // whoever reads this response has to know the data they will see is made up.
    const out: Record<string, unknown> = {
      modo: "sandbox",
      data: "synthetic, from Oura, not yours",
      base: base(),
    };
    try {
      // The pulse CANNOT be `personal_info`: it is the only one of the 19 the
      // sandbox does not serve, and asking for it would report an API as down
      // when it is up.
      const r = await fetchAll("daily_sleep", { start: "2026-01-01", end: "2026-01-03" });
      out["oura_responde"] = true;
      const data = r["data"] as Record<string, unknown>[];
      out["campos_de_ejemplo"] = data.length ? Object.keys(data[0]!).sort() : [];
    } catch (e) {
      out["oura_responde"] = false;
      out["error"] = (e as Error).message;
    }
    out["no_disponible_en_sandbox"] = ["personal_info"];
    out["siguiente_paso"] = "drop OURA_SANDBOX and set your own credential to see your data";
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
    // The field NAMES, not their values: confirms the API answers without
    // dumping anyone's profile into a log.
    const data = r["data"] as Record<string, unknown>[];
    out["campos_del_perfil"] = data.length ? Object.keys(data[0]!).sort() : [];
  } catch (e) {
    out["oura_responde"] = false;
    out["error"] = (e as Error).message;
  }
  return out;
}

export { SCOPE_OF };
