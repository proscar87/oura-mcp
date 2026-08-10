/**
 * Cliente de la API v2 de Oura. Sin dependencias fuera del SDK de MCP.
 *
 * THIS FILE IS THE PRODUCT. Oura never returns an error when it can't give you
 * what you asked for: it returns something different, shaped like a correct
 * response. These are the four we found by measuring against the real API, and
 * that are corrected here:
 *
 *   1. `next_token` sin seguir → recibes una fracción. Un día local de
 *      `heartrate` son 1,231 muestras en 2 páginas; quien no page recibe
 *      1,000 —el 81%— con aspecto de estar completo.
 *   2. `end_date` is INCONSISTENT ACROSS COLLECTIONS, and `workout` filters by
 *      UTC date while reporting `day` in local time. Asking for a single day
 *      returned ZERO records.
 *   3. `latest=true` where it doesn't apply → Oura returns the whole collection.
 *   4. `fields=made_up` → returns the complete record, no projection.
 *
 * Y un tercer final del bucle que casi se escapa: si Oura repite el mismo
 * `next_token`, eso es un cycle. Sin detectarlo se hacían 50 peticiones
 * idénticas con un warning que aconsejaba acortar el rango — consejo inútil,
 * porque acortar no arregla que la API se repita.
 */

import {
  SCOPE_OF, BASE, COLLECTIONS, WITH_DATE, WITH_LATEST, WITHOUT_SANDBOX, shape,
  type Shape,
} from "./collections.js";

export const TIMEOUT = 30_000;
export const PAGE_LIMIT = 50;   // ~50k records; more than that is a usage error
export const RETRIES_429 = 2;    // bounded: this runs inside a conversation
export const MAX_WAIT = 8_000; // ms; ni el `Retry-After` de Oura manda más

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

export function inSandbox(): boolean {
  const v = (process.env.OURA_SANDBOX ?? "").trim().toLowerCase();
  return v !== "" && !["0", "no", "false"].includes(v);
}

/**
 * A dónde se pide. Sandbox, override explícito, o Oura de verdad.
 *
 * EL SANDBOX ES OFICIAL, no un truco: está en el OpenAPI de Oura con 34 rutas
 * espejo, y acepta CUALQUIER cadena como `Authorization`. Permite instalar el
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
    // El sandbox acepta cualquier cadena. Pedir un token aquí sería inventar un
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
    if (!t) throw new OuraError(`OURA_PAT_FILE apunta a un archivo vacío: ${path}`);
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
    // EL MENSAJE IMPORTA. Antes mandaba a la página de tokens personales, y
    // desde diciembre de 2025 esa página ya no deja crear ninguno: quien
    // llegara ahí se quedaba atorado sin saber por qué. Ahora la primera opción
    // es la que funciona, y el sandbox va antes que nada porque permite ver el
    // srv andar sin conseguir credencial alguna.
    throw new OuraError(
      "no hay credenciales. Tres caminos, de menos a más trámite:\n" +
      "  1. OURA_SANDBOX=1 — data de ejemplo, sin registrarte en nada\n" +
      "  2. oura-mcp --authorize — OAuth2, una vez, en el navegador\n" +
      "  3. OURA_PAT / OURA_PAT_FILE — sólo si ya tenías un token personal: " +
      "Oura dejó de emitirlos en diciembre de 2025",
    );
  }
  if (!cred.expired()) return cred.access;
  const { appCredentials } = await import("./authorize.js");
  const [cid, csec] = appCredentials();
  return (await refresh(cred, cid, csec)).access;
}

// ── One request, with a bounded retry for the 429 only ─────────────────────
/** Lo legible del body de error de Oura, o el crudo recortado.
 *
 * Oura contesta `detail` de dos formas y ninguna se lee en crudo. Una es una
 * cadena; la otra es el arreglo de errores de validación de pydantic, cuyo JSON
 * pasa de los 200 characters antes de llegar a lo único que importa —qué campo
 * y por qué—, así que recortarlo dejaba
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

/** Cuánto esperar tras un 429: lo que diga `Retry-After`, o backoff. */
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
 * SÓLO el 429 se reintenta. Un 401 no mejora esperando y un 422 tampoco: lo
 * all retrying them achieves is taking three times as long to deliver the same
 * bad news.
 *
 * Oura NO manda cabeceras de límite de tasa en las respuestas buenas
 * —verificado el 9-ago-2026— así que un cliente no puede saber qué tan cerca
 * is to the ceiling. It only finds out once it's been refused, and by then it may
 * have 30 pages fetched that would be thrown away.
 */
export async function request(url: string, tok: Secret,
                            reintentos = RETRIES_429): Promise<Record<string, unknown>> {
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

    if (r.status === 429 && intento < reintentos) {
      await sleep(requestedWait(r.headers.get("Retry-After"), intento));
      continue;
    }
    const body = await r.text().catch(() => "");
    if (r.status === 401) {
      throw new OuraError("Oura rechazó el token (401). ¿Expiró la credencial?");
    }
    if (r.status === 429) {
      throw new OuraError(
        `Oura está limitando la tasa (429) y siguió limitándola tras ` +
        `${reintentos} reintentos. Espera un poco y acorta el rango.`);
    }
    throw new OuraError(`Oura respondió ${r.status}${detailOf(body)}`);
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
export function ignoredFields(fields: string[] | undefined, data: Row[]): string[] {
  if (!fields?.length || !data.length) return [];
  const present = new Set<string>();
  for (const r of data) for (const k of Object.keys(r)) present.add(k);
  return fields.filter((c) => !present.has(c)).sort();
}

/** If the response is enormous, say so and point at the field inflating it.
 *
 * Medido: 30 días de `daily_activity` son 252,000 characters, y el 92% de cada
 * registro es `met` —una serie de MET por minuto—. Pedir tres columns baja eso
 * a 5,000: 99% menos. No se recorta nada por cuenta propia —eso sería entregar
 * de menos— pero sí se dice qué pesa y cómo request menos.
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
  fields?: string[];
  latest?: boolean;
  format?: "json" | "csv";
  pageLimit?: number;
}

export async function fetchAll(collection: string, o: Options = {}): Promise<Row> {
  const { start, end, fields, latest = false, format = "json",
          pageLimit = PAGE_LIMIT } = o;
  const f = shape(collection);
  const params = new URLSearchParams();

  if (inSandbox() && WITHOUT_SANDBOX.has(collection)) {
    // Se atrapa ANTES de la petición. El sandbox contesta 404 a secas, y un
    // «404: Not Found» a quien acaba de instalar le dice que el srv está
    // roto — cuando lo que pasa es que Oura no pone data falsos de la única
    // colección con correo, edad, weight y estatura.
    throw new OuraError(
      `\`${collection}\` no existe en el sandbox de Oura: es la única de las 19 ` +
      `que no sirve, porque es la que devuelve data personales. Todo lo demás ` +
      `sí funciona aquí. Para ver la tuya de verdad, quita OURA_SANDBOX y corre ` +
      `\`oura-mcp --authorize\`.`);
  }

  if (latest) {
    // Oura NO se queja si se le manda `latest` a una colección que no lo
    // soporta: devuelve la colección entera. Pedir el último registro y recibir
    // diez creyendo que es uno es peor que un error.
    if (!WITH_LATEST.has(collection)) {
      throw new OuraError(
        `\`latest\` sólo lo respeta Oura en ${[...WITH_LATEST].sort().join(", ")}; ` +
        `en ${collection} lo ignora y devuelve la colección entera`);
    }
    params.set("latest", "true");
  }
  if (fields?.length) params.set("fields", fields.join(","));

  if (WITH_DATE.has(f) && !latest) {
    if (!start || !end) throw new OuraError(`${collection} necesita start y end`);
    if (start > end) {
      // Se atrapa AQUÍ y no en Oura porque el margen cambia las fechas: Oura
      // devolvería un 400 citando dos fechas que quien preguntó nunca escribió.
      throw new OuraError(
        `el rango va al revés: start (${start}) es posterior a end (${end})`);
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
  let truncated: string | undefined, cursor: string | undefined, cycle: string | undefined;
  const seen = new Set<string>();

  for (;;) {
    const q = new URLSearchParams(params);
    if (nextToken) q.set("next_token", nextToken);
    const qs = q.toString();
    const body = await request(`${root}/${collection}${qs ? `?${qs}` : ""}`, tok);
    pages++;

    // `personal_info` y `ring_configuration` no vienen envueltos en `data`: el
    // body ENTERO es el registro. Se distingue por la AUSENCIA de la clave.
    // Si `data` viene y no es lista, algo cambió en la API, y envolver el sobre
    // convertiría eso en «un registro» con shape `{data: …}` que se ve legítimo.
    if ("data" in body) {
      const crudo = body["data"];
      if (!Array.isArray(crudo)) {
        throw new OuraError(
          `Oura devolvió \`data\` como ${crudo === null ? "null" : typeof crudo} y no ` +
          `como lista en ${collection}. La shape de la respuesta cambió; no se ` +
          `inventa una interpretación.`);
      }
      data.push(...(crudo as Row[]));
    } else if (Object.keys(body).length) {
      data.push(body);
    }

    nextToken = body["next_token"] as string | undefined;
    if (!nextToken) break;
    if (seen.has(nextToken)) {
      // UN `next_token` QUE SE REPITE ES UN CICLO. Sin esto se hacían 50
      // peticiones idénticas, se devolvían 50 copias del mismo registro, y el
      // warning decía «acorta el rango» — consejo inútil, porque acortar no
      // arregla que la API se repita. No es truncamiento y no debe llamarse así.
      cycle = "Oura repitió el mismo `next_token`: eso es un cycle, y se paró " +
              "para no request lo mismo sin end. Lo que sigue llega hasta donde se " +
              "pudo avanzar y puede estar incompleto.";
      break;
    }
    seen.add(nextToken);
    if (pages >= pageLimit) {
      truncated = `se detuvo en ${pageLimit} páginas y Oura ofrecía más; ` +
                 `acorta el rango o sigue desde \`continuar_desde\``;
      cursor = nextToken;
      break;
    }
  }

  const trimmed = trim(data, start, end, f);
  data = trimmed.data;

  const out: Row = { collection, n: data.length, pages, data };
  if (truncated) { out["truncated"] = truncated; out["continue_from"] = cursor; }
  if (cycle) out["pagination_cycle"] = cycle;
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
  const ignored = ignoredFields(fields, data);
  if (ignored.length) out["ignored_fields"] = ignored;
  const warning = sizeWarning(data, fields);
  if (warning) out["large_response"] = warning;
  if (trimmed.discarded) out["discarded_out_of_range"] = trimmed.discarded;
  if (!data.length) out["empty"] = await whyEmpty(collection, start, end);
  return out;
}

export { COLLECTIONS, WITH_DATE, shape };
