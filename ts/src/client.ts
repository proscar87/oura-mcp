/**
 * Cliente de la API v2 de Oura. Sin dependencias fuera del SDK de MCP.
 *
 * THIS FILE IS THE PRODUCT. Oura never returns an error when it can't give you
 * what you asked for: it returns something different, shaped like a correct
 * response. These are the four we found by measuring against the real API, and
 * that are corrected here:
 *
 *   1. Not following `next_token` returns a fraction. One local day of
 *      `heartrate` is 1,231 samples across 2 pages; a client that doesn't
 *      paginate gets 1,000 — 81% — looking complete.
 *   2. `end_date` is INCONSISTENT ACROSS COLLECTIONS, and `workout` filters by
 *      UTC date while reporting `day` in local time. Asking for a single day
 *      returned ZERO records.
 *   3. `latest=true` where it doesn't apply → Oura returns the whole collection.
 *   4. `fields=made_up` → returns the complete record, no projection.
 *
 * And a third exit from the loop that nearly got away: if Oura repeats the same
 * `next_token`, that's a cycle. Without detecting it the client made 50
 * identical requests with a warning advising you to shorten the range — useless
 * advice, because shortening doesn't stop the API from repeating itself.
 */

import {
  SCOPE_OF, BASE, COLLECTIONS, WITH_DATE, WITH_LATEST, WITHOUT_SANDBOX, shape,
  type Shape,
} from "./collections.js";

export const TIMEOUT = 30_000;
export const PAGE_LIMIT = 50;   // ~50k records; more than that is a usage error
export const RETRIES_429 = 2;    // bounded: this runs inside a conversation
export const MAX_WAIT = 8_000; // ms; not even Oura's `Retry-After` gets more

/**
 * How many characters before the response comments on itself. 50,000 is roughly
 * 12,000 tokens: enough to matter, little enough not to nag. Measured: 30 days
 * of `daily_activity` is 252,000, and 92% of it is a single field.
 */
export const SIZE_WARNING = 50_000;

/**
 * Extra days requested on each side before trimming. TWO, not one: `workout` is
 * exclusive at the end AND skewed to UTC, and the two stack. The largest UTC
 * offset in the world is ±14 h — one day — and the exclusivity costs another.
 * Two covers any timezone.
 */
export const EXTRA_DAYS = 2;

const CLAVES_DIA = ["day", "start_day"] as const;
const CLAVES_HORA = ["timestamp", "start_time", "bedtime_start"] as const;

/** A failure talking to Oura. NEVER carries the token in its message. */
export class OuraError extends Error {
  constructor(mensaje: string) {
    super(mensaje);
    this.name = "OuraError";
  }
}

/**
 * A token that can't be printed by accident. Ask for it with `reveal()`.
 *
 * A string holding a token leaks out through too many places: a debug
 * `console.log` that was left behind, an exception dragging its context along, a
 * template literal written in a hurry. This already cost a token once, and the
 * lesson wasn't "be more careful": it was that care doesn't hold up by hand.
 */
export class Secret {
  readonly #valor: string;

  constructor(valor: string) {
    this.#valor = valor;
  }

  reveal(): string {
    return this.#valor;
  }

  get largo(): number {
    return this.#valor.length;
  }

  toString(): string {
    return `<secreto de ${this.#valor.length} characters>`;
  }

  toJSON(): string {
    return this.toString();
  }

  // Node prints this with console.log and in stack traces.
  [Symbol.for("nodejs.util.inspect.custom")](): string {
    return this.toString();
  }
}

/**
 * On every sandbox response. Sample data that reads as real is the exact
 * failure this server exists to correct, so it says so in band, where a
 * model must see it — not in the documentation, where nobody reads it.
 */
export const SYNTHETIC =
  "SANDBOX MODE: this is Oura's sample data, not this person's. Do not " +
  "report these numbers as their own. To see real data, turn off the " +
  "sample-data setting and connect an Oura account.";

export function inSandbox(): boolean {
  const v = (process.env.OURA_SANDBOX ?? "").trim().toLowerCase();
  return v !== "" && !["0", "no", "false"].includes(v);
}

/**
 * Where requests go. Sandbox, explicit override, or the real Oura.
 *
 * THE SANDBOX IS OFFICIAL, not a trick: it's in Oura's OpenAPI spec with 34
 * mirror routes, and it accepts ANY string as `Authorization`. It lets you install the
 * server and watch it work BEFORE fighting with authentication — which stopped
 * being a one-minute errand when Oura deprecated personal tokens in December
 * 2025.
 *
 * What the sandbox is NOT good for is measuring API behavior: it's a GENERATOR,
 * not a filter. It returns n-1 records for any window.
 */
export function base(): string {
  const override = (process.env.OURA_API_BASE_URL ?? "").trim();
  if (override) return override.replace(/\/+$/, "");
  if (inSandbox()) return BASE.replace("/v2/usercollection", "/v2/sandbox/usercollection");
  return BASE;
}

/** The day a record belongs to, or null if it can't be determined.
 *
 * `null` means "I don't know", and whoever filters must KEEP IT. Discarding what
 * you don't understand is the fastest way to under-deliver.
 */
export function dayOf(registro: unknown): string | null {
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

/** `YYYY-MM-DD` ± days. If it doesn't parse it's returned untouched: a
 * malformed date is rejected by Oura with a 422 explaining what it expected, and
 * that message is more useful than anything we could invent. */
export function shiftDays(fecha: string, dias: number): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(fecha);
  if (!m) return fecha;
  const d = new Date(Date.UTC(+m[1]!, +m[2]! - 1, +m[3]!));
  d.setUTCDate(d.getUTCDate() + dias);
  return d.toISOString().slice(0, 10);
}

// ── El token ────────────────────────────────────────────────────────────────
export async function token(): Promise<Secret> {
  if (inSandbox()) {
    // The sandbox accepts any string. Demanding a token here would invent a
    // requirement the API doesn't have, and that requirement loses exactly the
    // person who has no way to get one yet.
    return new Secret("sandbox");
  }
  const path = (process.env.OURA_PAT_FILE ?? "").trim();
  if (path) {
    const { readFile } = await import("node:fs/promises");
    const { homedir } = await import("node:os");
    let t: string;
    try {
      t = (await readFile(path.replace(/^~/, homedir()), "utf8")).trim();
    } catch (e) {
      throw new OuraError(`no se pudo leer OURA_PAT_FILE: ${(e as Error).message}`);
    }
    if (!t) throw new OuraError(`OURA_PAT_FILE points at an empty file: ${path}`);
    return new Secret(t);
  }
  const t = (process.env.OURA_PAT ?? "").trim();
  if (t) return new Secret(t);
  return oauthToken();
}

async function oauthToken(): Promise<Secret> {
  const { load, refresh } = await import("./credentials.js");
  const cred = await load();
  if (!cred) {
    // THE MESSAGE MATTERS. It used to point at the personal-tokens page,
    // and since December 2025 that page issues none: whoever
    // landed there got stuck without knowing why. Now the first option
    // is the one that works, and the sandbox comes first because it lets you
    // srv andar sin conseguir credencial alguna.
    throw new OuraError(
      "no credentials. Three paths, from least to most paperwork:\n" +
      "  1. OURA_SANDBOX=1 — sample data, no signup of any kind\n" +
      "  2. oura-mcp --authorize — OAuth2, once, in the browser\n" +
      "  3. OURA_PAT / OURA_PAT_FILE — only if you already had a personal token: " +
      "Oura stopped issuing them in December 2025",
    );
  }
  if (!cred.expired()) return cred.access;
  const { appCredentials } = await import("./authorize.js");
  const [cid, csec] = appCredentials();
  return (await refresh(cred, cid, csec)).access;
}

// ── One request, with a bounded retry for the 429 only ─────────────────────
/** Lo legible del body de error de Oura, o el raw recortado.
 *
 * Oura answers `detail` in two shapes and neither reads well raw. One is a
 * string; the other is pydantic's validation-error array, whose JSON
 * runs past 200 characters before reaching the only thing that matters — which
 * field and why — so trimming it left
 * `{"detail":[{"type":"datetime_from_date_parsing","loc":["query","star` y
 * and nothing else.
 */
export function detailOf(body: string): string {
  let d: unknown;
  try {
    d = (JSON.parse(body) as { detail?: unknown }).detail;
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
  return ": " + body.slice(0, 200);
}

/** How long to wait after a 429: whatever `Retry-After` says, or backoff. */
export function requestedWait(retryAfter: string | null, intento: number): number {
  if (retryAfter) {
    const segundos = Number(retryAfter.trim());
    if (Number.isFinite(segundos)) return Math.min(segundos * 1000, MAX_WAIT);
    const cuando = Date.parse(retryAfter);
    if (Number.isFinite(cuando)) {
      return Math.min(Math.max(cuando - Date.now(), 0), MAX_WAIT);
    }
  }
  return Math.min(2 ** intento * 1000, MAX_WAIT);
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/**
 * ONLY the 429 is retried. A 401 doesn't improve by waiting and neither does a
 * 422:
 * all retrying them achieves is taking three times as long to deliver the same
 * bad news.
 *
 * Oura sends NO rate-limit headers on successful responses
 * — verified 2026-08-09 — so a client can't know how close it
 * is to the ceiling. It only finds out once it's been refused, and by then it may
 * have 30 pages fetched that would be thrown away.
 */
export async function request(url: string, tok: Secret,
                            retries = RETRIES_429,
                            waits?: number[]): Promise<Record<string, unknown>> {
  for (let intento = 0; ; intento++) {
    let r: Response;
    try {
      r = await fetch(url, {
        headers: { Authorization: `Bearer ${tok.reveal()}`, Accept: "application/json" },
        signal: AbortSignal.timeout(TIMEOUT),
      });
    } catch (e) {
      throw new OuraError(`no se pudo alcanzar Oura: ${(e as Error).message}`);
    }
    if (r.ok) return (await r.json()) as Record<string, unknown>;

    if (r.status === 429 && intento < retries) {
      const pause = requestedWait(r.headers.get("Retry-After"), intento);
      // RECORD IT. A retry that SUCCEEDS left no trace: the caller waited, the
      // answer came back clean, and nothing said Oura had refused.
      waits?.push(pause);
      await sleep(pause);
      continue;
    }
    const body = await r.text().catch(() => "");
    if (r.status === 401) {
      throw new OuraError("Oura rejected the token (401). Did the credential expire?");
    }
    if (r.status === 429) {
      throw new OuraError(
        `Oura is rate limiting (429) and kept doing so after ` +
        `${retries} retries. Wait a bit and shorten the range.`);
    }
    throw new OuraError(`Oura responded ${r.status}${detailOf(body)}`);
  }
}

// ── CSV, avisos y recortes ─────────────────────────────────────────────────
type Row = Record<string, unknown>;

const cell = (v: unknown): string =>
  v === null || v === undefined ? "" :
  typeof v === "object" ? JSON.stringify(v) : String(v);

/**
 * Los registros como CSV. Un mes de `heartrate` son ~37,000 registros; en JSON
 * eso repite las mismas cuatro keys 37,000 veces.
 *
 * THE HEADER COMES FROM THE UNION OF ALL KEYS, not from the first record. Taking
 * it from the first is the easiest way to lose data here: one record with an
 * extra field is enough for that field to vanish without a trace.
 */
export function toCsv(data: Row[]): { text: string; columns: string[]; uneven: boolean } {
  const keys = new Set<string>();
  for (const r of data) for (const k of Object.keys(r)) keys.add(k);
  // The date first: it's the column a model joins against another source with,
  // and hunting for it mid-table is friction for no reason.
  const front = ["day", "timestamp", "start_day", "id"].filter((k) => keys.has(k));
  const columns = [...front, ...[...keys].filter((k) => !front.includes(k)).sort()];
  const uneven = data.some((r) => Object.keys(r).length !== keys.size);

  const escapeCell = (s: string) => (/[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s);
  const rows = [columns.map(escapeCell).join(",")];
  for (const r of data) rows.push(columns.map((c) => escapeCell(cell(r[c]))).join(","));
  return { text: rows.join("\n") + "\n", columns, uneven };
}

/** The requested fields that showed up in no record.
 *
 * Oura does NOT complain about a field name that doesn't exist:
 * `fields=made_up` returns the COMPLETE record — the projection never happens —
 * and `fields=score,made_up`
 * applies the good one and drops the bad one without a word. In both cases the
 * asker believes they filtered and didn't.
 */
export const FIELDS_NOTE =
  "`fields` arrived as a comma-separated string and was split. Models send " +
  "\"day,score\" far more often than [\"day\", \"score\"], and the raw schema " +
  "error for that is a validator dump — the opposite of what this server is " +
  "for. No Oura field name contains a comma, so splitting is unambiguous.";

/**
 * Accept a list OR a comma-separated string.
 *
 * THE MOST LIKELY MISTAKE ON THIS TOOL. Declared as `string[]`, a model sending
 * `"day,score"` got a raw validator error pointing at a library's docs site —
 * technically correct, and not an answer. No Oura field name contains a comma.
 */
export function asFields(fields: string[] | string | undefined): string[] | undefined {
  if (fields === undefined) return undefined;
  const list = typeof fields === "string"
    ? fields.split(",").map((f) => f.trim()).filter(Boolean)
    : [...fields];
  return list.length ? list : undefined;
}

export function ignoredFields(fields: string[] | undefined, data: Row[]): string[] {
  if (!fields?.length || !data.length) return [];
  const present = new Set<string>();
  for (const r of data) for (const k of Object.keys(r)) present.add(k);
  return fields.filter((c) => !present.has(c)).sort();
}

/** If the response is enormous, say so and point at the field inflating it.
 *
 * Measured: 30 days of `daily_activity` is 252,000 characters, and 92% of each
 * record is `met` — a per-minute MET series. Asking for three columns brings
 * that down to 5,000: 99% less. Nothing is trimmed on our own initiative — that
 * would be under-delivering — but what's heavy is named, and how to ask for less.
 */
export function sizeWarning(data: Row[], fields: string[] | undefined) {
  if (fields?.length || data.length < 2) return null;
  let total = 0;
  const weights = new Map<string, number>();
  for (const r of data) {
    for (const [k, v] of Object.entries(r)) {
      const n = JSON.stringify(v)?.length ?? 0;
      weights.set(k, (weights.get(k) ?? 0) + n);
      total += n;
    }
  }
  if (total < SIZE_WARNING) return null;
  let heaviest = "", weight = 0;
  for (const [k, n] of weights) if (n > weight) { heaviest = k; weight = n; }
  const pct = total ? Math.round((weight * 100) / total) : 0;
  return {
    characters: total,
    heaviest_field: heaviest,
    percentage: pct,
    suggestion: `\`${heaviest}\` takes up ${pct}% of this response. If you don't ` +
      `need it, ask only for the columns you use with \`fields\`, or shorten the range.`,
  };
}

/** Keep only records whose `day` falls in [start, end].
 *
 * A record whose day CANNOT be determined is kept. This filter exists to correct
 * a deliberate widening, not to decide what counts as valid data — discarding
 * what you don't understand is the fastest way to under-deliver, which is
 * precisely what this package exists not to do.
 */
function trim(data: Row[], start: string | undefined, end: string | undefined,
                  f: Shape): { data: Row[]; discarded: number } {
  if (f !== "dateRange" || !start || !end) return { data, discarded: 0 };
  const floor = start.slice(0, 10), ceiling = end.slice(0, 10);
  const inside = data.filter((r) => {
    const d = dayOf(r);
    return d === null || (d >= floor && d <= ceiling);
  });
  return { data: inside, discarded: data.length - inside.length };
}

/** What is known when the query comes back with nothing.
 *
 * `n: 0` is the most common answer to the most common questions — "how did I
 * sleep last night?", "am I recovered?" — and it doesn't distinguish between
 * four things that lead to opposite conclusions: you weren't wearing the ring,
 * it hasn't synced, you asked for a future date, or your token lacks that scope.
 * A model receiving `{n: 0}` will answer "you didn't sleep" with complete
 * confidence, and may be wrong.
 *
 * This does NOT guess which one: it lists what can be checked without going to
 * the network.
 */
async function whyEmpty(collection: string, start?: string, end?: string) {
  const today = new Date().toISOString().slice(0, 10);
  const reasons: string[] = [];
  if (start && end) {
    if (start.slice(0, 10) > today) reasons.push("the requested range is in the future");
    else if (end.slice(0, 10) >= today) {
      reasons.push(
        "the range reaches today, and Oura's data only appears once the ring " +
        "syncs with the app; the current day is usually missing or incomplete");
    }
  }
  const scope = SCOPE_OF[collection];
  const withPat = process.env.OURA_PAT || process.env.OURA_PAT_FILE;
  if (scope && !inSandbox() && !withPat) {
    try {
      const { load } = await import("./credentials.js");
      const cred = await load();
      if (cred && !cred.scopes.includes(scope)) {
        reasons.push(
          `this collection needs the \`${scope}\` scope and your credentials ` +
          `don't have it: run \`oura-mcp --authorize\` again and grant it`);
      }
    } catch { /* if they can't be read, no reason is invented */ }
  }
  return {
    no_data: "the query succeeded; Oura has no records in that range",
    what_we_know: reasons.length ? reasons : ["nothing further to report without hitting the network"],
    do_not_confuse: "«no data» is not the same as «you didn't sleep» or «you didn't " +
      "recover». To find out whether the ring has data nearby, ask for a wider range.",
  };
}

// ── `fetchAll`: the loop that is the product ───────────────────────────────
export interface Options {
  start?: string;
  end?: string;
  fields?: string[] | string;
  latest?: boolean;
  format?: "json" | "csv";
  pageLimit?: number;
}

export async function fetchAll(collection: string, o: Options = {}): Promise<Row> {
  const { start, end, fields: rawFields, latest = false, format = "json",
          pageLimit = PAGE_LIMIT } = o;
  const wasString = typeof rawFields === "string";
  const fields = asFields(rawFields);
  const f = shape(collection);
  const params = new URLSearchParams();

  if (inSandbox() && WITHOUT_SANDBOX.has(collection)) {
    // Caught BEFORE the request. The sandbox answers a bare 404, and a
    // "404: Not Found" tells someone who just installed that the server is
    // broken — when what's actually happening is that Oura publishes no fake
    // data for the one collection carrying email, age, weight and height.
    throw new OuraError(
      `\`${collection}\` does not exist in Oura's sandbox: it is the only one of ` +
      `the 19 not served there, because it is the one returning personal data. ` +
      `Everything else works here. To see your real one, drop OURA_SANDBOX and ` +
      `run \`oura-mcp --authorize\`.`);
  }

  if (latest) {
    // Oura does NOT complain when `latest` is sent to a collection that doesn't
    // support it: it returns the entire collection. Asking for the latest record
    // and receiving ten while believing it's one is worse than an error.
    if (!WITH_LATEST.has(collection)) {
      throw new OuraError(
        `\`latest\` is only honored by Oura on ${[...WITH_LATEST].sort().join(", ")}; ` +
        `on ${collection} it is ignored and the whole collection comes back`);
    }
    params.set("latest", "true");
  }
  if (fields?.length) params.set("fields", fields.join(","));

  if (WITH_DATE.has(f) && !latest) {
    if (!start || !end) throw new OuraError(`${collection} necesita start y end`);
    if (start > end) {
      // Caught HERE and not at Oura because the margin changes the dates: Oura
      // would return a 400 quoting two dates the asker never wrote.
      throw new OuraError(
        `the range runs backwards: start (${start}) is after end (${end})`);
    }
    if (f === "dateRange") {
      params.set("start_date", shiftDays(start, -EXTRA_DAYS));
      params.set("end_date", shiftDays(end, +EXTRA_DAYS));
    } else {
      params.set("start_datetime", start);
      params.set("end_datetime", end);
    }
  }

  const root = base();
  const tok = await token();
  let data: Row[] = [];
  let pages = 0, nextToken: string | undefined;
  const waits: number[] = [];
  let truncated: string | undefined, cursor: string | undefined, cycle: string | undefined;
  const seen = new Set<string>();

  for (;;) {
    const q = new URLSearchParams(params);
    if (nextToken) q.set("next_token", nextToken);
    const qs = q.toString();
    const body = await request(`${root}/${collection}${qs ? `?${qs}` : ""}`, tok,
                               RETRIES_429, waits);
    pages++;

    // `personal_info` y `ring_configuration` no vienen envueltos en `data`: el
    // body ENTERO es el registro. Se distingue por la AUSENCIA de la clave.
    // If `data` arrives and isn't a list, something changed in the API, and
    // wrapping the envelope would turn that into "one record" shaped like
    // `{data: …}` that looks legitimate.
    if ("data" in body) {
      const raw = body["data"];
      if (!Array.isArray(raw)) {
        throw new OuraError(
          `Oura returned \`data\` as ${raw === null ? "null" : typeof raw} rather ` +
          `than a list on ${collection}. The response shape changed; no ` +
          `interpretation is being invented.`);
      }
      data.push(...(raw as Row[]));
    } else if (Object.keys(body).length) {
      data.push(body);
    }

    nextToken = body["next_token"] as string | undefined;
    if (!nextToken) break;
    if (seen.has(nextToken)) {
      // A REPEATED `next_token` IS A CYCLE. Without this the client made 50
      // identical requests, returned 50 copies of the same record, and the
      // warning said "shorten the range" — useless advice, because shortening
      // doesn't stop the API from repeating itself. This isn't truncation and
      // mustn't be called that.
      cycle = "Oura repeated the same `next_token`: that is a cycle, and it " +
              "stopped rather than ask for the same thing forever. What follows " +
              "reaches as far as it got and may be incomplete.";
      break;
    }
    seen.add(nextToken);
    if (pages >= pageLimit) {
      // `continue_from` USED TO BE nextToken, and no parameter accepts a
      // token back — deliberately, since taking a cursor would make
      // pagination the model's job, which is what this package exists to
      // prevent. So the response told the model to continue from something
      // it could not use: an instruction that reads as actionable and is not.
      //
      // A day is usable with the parameters that already exist.
      cursor = (data.length ? dayOf(data[data.length - 1]) : undefined) ?? undefined;
      truncated = cursor
        ? `stopped at ${pageLimit} pages and Oura was offering more. The ` +
          `data reaches through ${cursor}; ask again with \`start\` set to ` +
          `the following day.`
        : `stopped at ${pageLimit} pages and Oura was offering more; ` +
          `narrow the range and ask again.`;
      break;
    }
  }

  const trimmed = trim(data, start, end, f);
  data = trimmed.data;

  const out: Row = { collection, n: data.length, pages, data };
  if (truncated) {
    out["truncated"] = truncated;
    // Only when there IS a day. `continue_from: null` reads as "resuming is
    // possible and the value is missing", worse than not offering it at all.
    if (cursor) out["continue_from"] = cursor;
  }
  if (cycle) out["pagination_cycle"] = cycle;
  if (waits.length) {
    // A SUCCESSFUL retry left no trace: the caller waited, the answer came
    // back clean, and nothing said Oura had refused. The data is correct, so
    // this is not the same bug as the other four — but being throttled means
    // the NEXT query may fail, and a model that does not know it was just
    // refused will happily fire off another fifty pages.
    const total = waits.reduce((a, b) => a + b, 0);
    out["rate_limited"] =
      `Oura refused ${waits.length} time(s) with 429 and this recovered after ` +
      `waiting ${total.toFixed(0)}s in total. The data is complete. You are ` +
      `near Oura's limit: make the next range smaller, or wait.`;
  }
  if (format === "csv") {
    const { text, columns, uneven } = toCsv(data);
    out["data"] = text;
    out["format"] = "csv";
    out["columns"] = columns;
    if (uneven) {
      out["uneven_columns"] =
        "not every record carries the same keys; an empty cell may be an " +
        "absent field or a null value";
    }
  }
  if (wasString) out["fields_split"] = FIELDS_NOTE;
  const ignored = ignoredFields(fields, data);
  if (ignored.length) out["ignored_fields"] = ignored;
  const warning = sizeWarning(data, fields);
  if (warning) out["large_response"] = warning;
  if (trimmed.discarded) {
    // AS A BARE NUMBER IT READ AS DATA LOSS. It fires on essentially every dated
    // query — two extra days are always requested on each side and always
    // trimmed — so it reports the safety margin working, not a problem.
    out["discarded_out_of_range"] =
      `${trimmed.discarded} record(s) from the ±${EXTRA_DAYS}-day safety margin ` +
      `were trimmed. This is normal and nothing you asked for is missing: the ` +
      `margin exists because Oura's \`end_date\` is inconsistent across collections.`;
  }
  if (!data.length) out["empty"] = await whyEmpty(collection, start, end);
  if (inSandbox()) {
    // EVERY sandbox response says so. `oura_check` said it and the queries did
    // not, so someone asking "how did I sleep?" got a score out of Oura's fake
    // data with nothing marking it — this package's own thesis, committed by
    // us, in the default configuration. A model reading this key cannot report
    // synthetic numbers as the person's own, and it names the next step.
    out["synthetic"] = SYNTHETIC;
  }
  return out;
}

export { COLLECTIONS, WITH_DATE, shape };
