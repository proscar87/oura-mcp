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
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { z } from "zod";

import { OuraError, base, inSandbox, fetchAll, token } from "./client.js";
import { SCOPE_OF, COLLECTIONS, WITH_DATE, shape, shapeName } from "./collections.js";

// READ FROM package.json, never typed here. This constant said 0.3.0 while
// every other declaration said 0.3.2, and it is the one the MCP handshake
// reports — so the bundle told each client a version that had not existed for
// two releases. Exactly the bug the audit fixed in Python ("the server lied
// about its version"), recurring in the half that ships inside the .mcpb,
// because the coherence test pinned the manifest and package.json and not this.
export const VERSION: string = (() => {
  try {
    const here = dirname(fileURLToPath(import.meta.url));
    return JSON.parse(readFileSync(join(here, "..", "package.json"), "utf8")).version;
  } catch {
    // Packed layouts move package.json around; an honest "unknown" beats a
    // confident wrong number in a bug report.
    return "unknown";
  }
})();

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
  // AHEAD OF THE FOUR, not among them. The other four are about whether the
  // data is complete; this one is about WHOSE it is, a different question and a
  // worse mistake. Sample data is on by default in the desktop bundle, and the
  // instructions named `empty`, `truncated` and `large_response` while never
  // mentioning `synthetic` — so the most consequential key in the default
  // configuration was the one a model was never told to look for.
  "BEFORE ANYTHING ELSE: if a response carries `synthetic`, the numbers in it " +
  "are Oura's sample data and NOT this person's. Say so plainly and never " +
  "report them as their own. Sample data is on by default so the server works " +
  "before anyone has an account.\n\n" +
  "FOUR THINGS THAT CHANGE THE ANSWER:\n\n" +
  "1. `n: 0` does NOT mean the person didn't sleep, didn't move or didn't " +
  "recover. It means Oura has no records in that range, and the most common " +
  "cause is that the ring hasn't synced yet — the current day is almost always " +
  "missing. When that happens the response carries `empty` with what is known. " +
  "Read it before concluding anything, and say there is no data, not that it " +
  "didn't happen.\n\n" +
  "2. If `truncated` appears, data is MISSING: `continue_from` is the last day " +
  "reached, and you ask again with `start` set to the day after. If " +
  "`pagination_cycle` " +
  "appears, Oura repeated itself and what you have may be incomplete. Neither " +
  "one gets ignored.\n\n" +
  "3. The range is inclusive on both ends, and `day` is the shorthand for a " +
  "single one. To join a workout with the heart rate during it: request " +
  "`workout`, take `start_datetime` and `end_datetime` from the one you care " +
  "about, and use them verbatim as `start` and `end` of `heartrate`.\n\n" +
  "4. Some collections are enormous: 30 days of `daily_activity` is 250,000 " +
  "characters, and 92% of it is a single field. If the response carries " +
  "`large_response`, ask again with `fields` limited to what you need.\n\n" +
  "This server deliberately computes no averages and no trends: it hands over " +
  "the data so the analysis happens where the method can be cited.";

// The connected server, kept so the tool handlers can reach the client.
let live: McpServer | undefined;

export function enableElicitation(server: McpServer): void {
  live = server;
}

/**
 * The client's URL-elicitation channel, or undefined if it hasn't got one.
 *
 * RESOLVED AT CALL TIME, not at startup. `connect()` returns once the transport
 * is wired, and the client's capabilities aren't known until its `initialize`
 * arrives — so asking at startup always saw nothing and the flow silently never
 * ran. Asked here, at the moment credentials turn out to be missing, the answer
 * is real.
 */
function elicitationChannel() {
  const low = live?.server;
  // Only when the client says it can: asking one that cannot show a URL turns a
  // clear "no credentials" message into a protocol error.
  if (!low?.getClientCapabilities?.()?.elicitation) return undefined;
  return {
    elicit: (p: { mode: "url"; message: string; elicitationId: string; url: string }) =>
      low.elicitInput(p),
    done: async (id: string) => { await low.createElicitationCompletionNotifier(id)(); },
  };
}

/**
 * The ring, embedded, or nothing at all.
 *
 * EMBEDDED RATHER THAN LINKED, deliberately. An `https://…` icon makes every
 * client fetch it from GitHub on every session — a request that tells a third
 * party «somebody is using this right now», from a health server that promises
 * no telemetry. 16 KB down a local pipe, once, is the cheaper end of that trade.
 *
 * On the SERVER only, not on each tool: four copies of the same ring is three
 * copies of nothing.
 *
 * Returns undefined if the file isn't there — the packed bundle and the source
 * tree put it at different depths. An icon is decoration and must never be the
 * reason a server fails to start.
 */
function icons(): { src: string; mimeType: string; sizes: string[] }[] | undefined {
  for (const ruta of ["../icon.png", "../../icon.png"]) {
    try {
      const aqui = dirname(fileURLToPath(import.meta.url));
      const b64 = readFileSync(join(aqui, ruta)).toString("base64");
      return [{ src: `data:image/png;base64,${b64}`,
                mimeType: "image/png", sizes: ["512x512"] }];
    } catch { /* try the next layout */ }
  }
  return undefined;
}

export function createServer(): McpServer {
  const srv = new McpServer(
    { name: "oura", version: VERSION, icons: icons() },
    { instructions: INSTRUCTIONS },
  );

  srv.registerTool("oura_collections", {
    title: "Oura collection catalog",
    description:
      "The 19 Oura collections, what each one carries and which parameters it " +
      "takes. Use it before `oura_query` if you are unsure of the exact name.",
    inputSchema: {},
    annotations: { title: "Oura collection catalog", ...READ_ONLY },
  }, async () => {
    const catalog = Object.fromEntries(
      Object.entries(COLLECTIONS).map(([n, c]) => [n, { shape: shapeName(c.shape), carries: c.carries }]),
    );
    return { content: [{ type: "text", text: JSON.stringify(catalog, null, 2) }] };
  });

  // THE SAME CATALOG AS A RESOURCE. The most likely mistake on this server is
  // inventing a collection name — the error for it exists and lists all
  // nineteen, which is an admission that it was expected. A resource puts the
  // list in front of the model BEFORE the mistake instead of after it, and
  // costs no round trip. Static: no network, no credentials, no health data.
  srv.registerResource("oura-collections", "oura://collections", {
    title: "Oura collection catalog",
    description: "The 19 collections, what each carries and which parameters " +
                 "it takes. Static: no network, no credentials, no health data.",
    mimeType: "application/json",
  }, async (uri) => {
    const catalog = Object.fromEntries(
      Object.entries(COLLECTIONS).map(([n, c]) => [n, { shape: shapeName(c.shape), carries: c.carries }]),
    );
    return { contents: [{ uri: uri.href, mimeType: "application/json",
                          text: JSON.stringify(catalog, null, 2) }] };
  });

  srv.registerTool("oura_query", {
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
      collection: z.string().describe("Exact name. See `oura_collections` if you are unsure."),
      day: z.string().optional().describe("Shorthand for a single day: equivalent to start=end=day."),
      start: z.string().optional().describe("AAAA-MM-DD, o ISO 8601 con hora"),
      end: z.string().optional().describe("AAAA-MM-DD, o ISO 8601 con hora"),
      fields: z.union([z.array(z.string()), z.string()]).optional().describe(
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

  srv.registerTool("oura_check", {
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
  // A list or a comma-separated string: models send "day,score" far more often
  // than ["day","score"], and the validator error for that is a dump, not an
  // answer. `asFields` normalizes it and the response says it happened.
  fields?: string[] | string;
  latest?: boolean;
  format?: "json" | "csv";
}

export async function query(a: QueryArgs): Promise<Record<string, unknown>> {
  if (!(a.collection in COLLECTIONS)) {
    return {
      error: `«${a.collection}» is not an Oura collection`,
      available: Object.keys(COLLECTIONS).sort(),
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
    // NO CREDENTIALS IS NOT AN ERROR THE USER SHOULD HAVE TO FIX BY HAND. If the
    // client can show a URL and this machine has app credentials, the OAuth flow
    // runs from inside the conversation: the client opens Oura's page, the
    // server listens for the callback it already knows how to listen for, and
    // the original request is retried. A `.mcpb` installed with a double click
    // must not end in a terminal.
    const channel = e instanceof OuraError && /no credentials/.test(e.message)
      ? elicitationChannel() : undefined;
    if (channel) {
      try {
        const { authorizeByElicitation } = await import("./authorize.js");
        await authorizeByElicitation(channel.elicit, channel.done);
        return await fetchAll(a.collection, {
          start, end, fields: a.fields, latest: a.latest, format: a.format,
        });
      } catch (e2) {
        if (e2 instanceof OuraError) return { error: e2.message };
        throw e2;
      }
    }
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
      granted_scopes: [...cred.scopes],
      ungranted_scopes: SCOPES.filter((a) => !cred.scopes.includes(a)),
      access_expires_in_seconds: Math.round((cred.expiresAt - Date.now()) / 1000),
      refreshes_itself: cred.refreshToken !== null,
    };
  } catch (e) {
    return { credentials: `unreadable: ${(e as Error).message}` };
  }
}

export async function check(): Promise<Record<string, unknown>> {
  if (inSandbox()) {
    // In sandbox there is no token to check and it mustn't look like there is:
    // whoever reads this response has to know the data they will see is made up.
    const out: Record<string, unknown> = {
      mode: "sandbox",
      data: "synthetic, from Oura, not yours",
      base: base(),
    };
    try {
      // The pulse CANNOT be `personal_info`: it is the only one of the 19 the
      // sandbox does not serve, and asking for it would report an API as down
      // when it is up.
      const r = await fetchAll("daily_sleep", { start: "2026-01-01", end: "2026-01-03" });
      out["oura_responds"] = true;
      const data = r["data"] as Record<string, unknown>[];
      out["sample_fields"] = data.length ? Object.keys(data[0]!).sort() : [];
    } catch (e) {
      out["oura_responds"] = false;
      out["error"] = (e as Error).message;
    }
    out["unavailable_in_sandbox"] = ["personal_info"];
    out["next_step"] = "drop OURA_SANDBOX and set your own credential to see your data";
    return out;
  }

  let t;
  try {
    t = await token();
  } catch (e) {
    return { token_present: false, next_step: (e as Error).message };
  }
  const out: Record<string, unknown> = {
    token_present: true,
    token_length: t.length,
    mode: authMode(),
    ...(await oauthState()),
  };
  try {
    const r = await fetchAll("personal_info");
    out["oura_responds"] = true;
    // The field NAMES, not their values: confirms the API answers without
    // dumping anyone's profile into a log.
    const data = r["data"] as Record<string, unknown>[];
    out["profile_fields"] = data.length ? Object.keys(data[0]!).sort() : [];
  } catch (e) {
    out["oura_responds"] = false;
    out["error"] = (e as Error).message;
  }
  return out;
}

export { SCOPE_OF };
