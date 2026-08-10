/**
 * Where the OAuth2 tokens live, and how they rotate without losing the session.
 *
 * THE DANGER IS IN A SINGLE LINE. Oura's refresh token is **single-use**: when
 * it's exchanged, Oura invalidates it and issues a new one. Between those two
 * things there's a window where the old one no longer works and the new one
 * isn't saved yet — and if the process dies there, the session is lost and you
 * have to authorize from the browser again.
 *
 * That's why `refresh()` saves BEFORE returning, atomically. You can't do
 * better: Oura offers no two-phase exchange. What you can do is make the window
 * as short as possible and ensure a half-written file never exists.
 */

import { chmod, mkdir, readFile, rename, rm, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { dirname, isAbsolute, join, resolve } from "node:path";

import { OuraError, Secret } from "./client.js";

export const TOKEN_URL = "https://api.ouraring.com/oauth/token";
export const AUTHORIZE_URL = "https://cloud.ouraring.com/oauth/authorize";
export const REVOKE_URL = "https://api.ouraring.com/oauth/revoke";

/**
 * The trailing slash is NOT a style detail: Oura's portal rejects `…/callback`
 * with `invalid_redirect_uri` and accepts `…/callback/`.
 */
export const DEFAULT_REDIRECT = "http://localhost:9876/callback/";

export const SCOPES = ["email", "personal", "daily", "heartrate", "workout",
                         "tag", "session", "spo2"] as const;

/**
 * Margin before treating an access token as expired. One that expires in three
 * seconds is, practically speaking, already expired: the request launched with
 * it will arrive late.
 */
export const EXPIRY_MARGIN = 60_000;

/** Where the file lives. `OURA_CREDENTIALS` moves it.
 *
 * ALWAYS ABSOLUTE. A bare relative path — `OURA_CREDENTIALS=cred.json`, which is
 * exactly what someone would write — would make the credentials depend on the
 * directory the server was started from, which in an MCP client is not the one
 * you think.
 */
export function credentialsPath(): string {
  const explicita = (process.env.OURA_CREDENTIALS ?? "").trim();
  if (explicita) {
    const expandida = explicita.replace(/^~/, homedir());
    return isAbsolute(expandida) ? expandida : resolve(expandida);
  }
  const base = process.env.XDG_CONFIG_HOME || join(homedir(), ".config");
  return join(base, "oura-mcp", "credenciales.json");
}

export class Credentials {
  constructor(
    readonly access: Secret,
    readonly refreshToken: Secret | null,
    readonly expiresAt: number,              // epoch en ms
    readonly scopes: readonly string[] = [],
  ) {}

  expired(margen = EXPIRY_MARGIN): boolean {
    return Date.now() + margen >= this.expiresAt;
  }

  asJson() {
    return {
      access: this.access.reveal(),
      refreshToken: this.refreshToken?.reveal() ?? null,
      expira_en: this.expiresAt,
      scopes: [...this.scopes],
    };
  }

  static fromJson(d: Record<string, unknown>): Credentials {
    if (typeof d["access"] !== "string") throw new Error("sin `access`");
    return new Credentials(
      new Secret(d["access"]),
      typeof d["refreshToken"] === "string" ? new Secret(d["refreshToken"]) : null,
      Number(d["expira_en"] ?? 0),
      Array.isArray(d["scopes"]) ? (d["scopes"] as string[]) : [],
    );
  }

  /** Neither the access nor the refresh token leaves this method. */
  toString(): string {
    const when = this.expired(0)
      ? "expired"
      : `valid for ${Math.round((this.expiresAt - Date.now()) / 1000)}s`;
    return `<Credentials ${when}, refreshToken=${this.refreshToken ? "yes" : "no"}, ` +
           `scopes=${this.scopes.length}>`;
  }

  [Symbol.for("nodejs.util.inspect.custom")](): string {
    return this.toString();
  }
}

/** Persists the credentials. Writes ATOMICALLY.
 *
 * A half-written credentials file is worse than none: the old refresh token has
 * already been consumed, and the new one was the only thing that could have
 * saved the session.
 */
export async function save(cred: Credentials): Promise<string> {
  const path = credentialsPath();
  await mkdir(dirname(path), { recursive: true, mode: 0o700 });
  const tmp = `${path}.${process.pid}.tmp`;
  try {
    await writeFile(tmp, JSON.stringify(cred.asJson()), { mode: 0o600 });
    await chmod(tmp, 0o600);   // in case umask interfered
    await rename(tmp, path);   // atomic within the same filesystem
  } catch (e) {
    await rm(tmp, { force: true });
    throw e;
  }
  return path;
}

export async function load(): Promise<Credentials | null> {
  const path = credentialsPath();
  let raw: string;
  try {
    raw = await readFile(path, "utf8");
  } catch (e) {
    if ((e as NodeJS.ErrnoException).code === "ENOENT") return null;
    throw new OuraError(
      `the credentials file could not be read. Delete it and authorize again: ${path}`);
  }
  try {
    return Credentials.fromJson(JSON.parse(raw) as Record<string, unknown>);
  } catch {
    throw new OuraError(
      `the credentials file is corrupt. Delete it and authorize again: ${path}`);
  }
}

export async function forget(): Promise<void> {
  await rm(credentialsPath(), { force: true });
}

// ── The exchange, which is where the session is lost if done wrong ────────
export async function post(data: Record<string, string>): Promise<Record<string, unknown>> {
  let r: Response;
  try {
    r = await fetch(TOKEN_URL, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded", Accept: "application/json" },
      body: new URLSearchParams(data).toString(),
      signal: AbortSignal.timeout(30_000),
    });
  } catch (e) {
    throw new OuraError(`could not reach Oura: ${(e as Error).message}`);
  }
  if (r.ok) return (await r.json()) as Record<string, unknown>;

  // Oura answers `{"error": …, "error_description": …}`. The description is
  // the actionable part — "Invalid client_id." — and burying it inside raw
  // JSON forces whoever is already stuck to read it.
  const texto = await r.text().catch(() => "");
  let detail = texto.slice(0, 200);
  try {
    const c = JSON.parse(texto) as { error?: string; error_description?: string };
    detail = c.error_description ?? c.error ?? detail;
  } catch { /* se queda el raw */ }
  throw new OuraError(`Oura rejected the exchange (${r.status}): ${detail}`);
}

function fromResponse(r: Record<string, unknown>, previous: readonly string[] = []): Credentials {
  if (typeof r["access_token"] !== "string") {
    throw new OuraError("Oura responded without `access_token`");
  }
  // The consent screen returns the GRANTED scopes, which aren't always the
  // requested ones. What Oura says it gave is stored, not what we believed we
  // asked for: the self-check relies on this.
  const granted = String(r["scope"] ?? "").split(/\s+/).filter(Boolean);
  return new Credentials(
    new Secret(r["access_token"]),
    typeof r["refresh_token"] === "string" ? new Secret(r["refresh_token"]) : null,
    Date.now() + Number(r["expires_in"] ?? 3600) * 1000,
    granted.length ? granted : [...previous],
  );
}

export async function exchangeCode(code: string, clientId: string, clientSecret: string,
                                    redirectUri = DEFAULT_REDIRECT): Promise<Credentials> {
  const cred = fromResponse(await post({
    grant_type: "authorization_code",
    code: code,
    redirect_uri: redirectUri,
    client_id: clientId,
    client_secret: clientSecret,
  }));
  await save(cred);
  return cred;
}

/**
 * Renews the pair and SAVES IT BEFORE RETURNING IT.
 *
 * The order is the whole point. The moment this request goes out, the refresh
 * token we held is dead. If the process died between the response and the save,
 * the session would be lost.
 *
 * If the exchange fails, what's on disk is re-read before declaring the session
 * lost: two processes refreshing at once is a real case — two MCP tools called
 * in parallel — and the one that loses the race would see a 400 even though the
 * session is perfectly alive, already renewed by the other.
 */
export async function refresh(cred: Credentials, clientId: string,
                                clientSecret: string): Promise<Credentials> {
  if (!cred.refreshToken) {
    throw new OuraError("no hay refresh token; hay que authorize de nuevo");
  }
  let r: Record<string, unknown>;
  try {
    r = await post({
      grant_type: "refresh_token",
      refresh_token: cred.refreshToken.reveal(),
      client_id: clientId,
      client_secret: clientSecret,
    });
  } catch (e) {
    const otra = await load().catch(() => null);
    if (otra?.refreshToken && !otra.expired()) return otra;   // somebody else already refreshed
    throw e;
  }
  const nueva = fromResponse(r, cred.scopes);
  await save(nueva);          // BEFORE returning. Do not move this line.
  return nueva;
}
