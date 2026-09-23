/**
 * The front door: this Worker's own consent screen, then Oura's login.
 *
 * THREE ATTACKS SHAPE EVERY LINE HERE, and each has one guard.
 *
 * 1. THE CONFUSED DEPUTY. Any MCP client can register itself (DCR or a Client
 *    ID Metadata Document) with any redirect URI. An attacker registers one
 *    pointing at their own server and sends the owner a link. Oura, which the
 *    owner already approved once, skips its consent screen — so without a
 *    screen of our own the owner's authorization would flow straight to the
 *    attacker. GUARD: nobody is sent to Oura until the owner has seen the
 *    client's name and exactly where it will send the result, and clicked.
 *
 * 2. A FORGED APPROVAL. A page elsewhere could auto-submit the approval form in
 *    the owner's browser. GUARD: the approval must carry a cookie set when the
 *    consent page was SHOWN, `SameSite=Lax` so a cross-site POST never carries
 *    it, and an `Origin` that is this Worker.
 *
 * 3. A SPLICED CALLBACK. An attacker starts a flow of their own, approves it,
 *    and sends the owner the resulting Oura link: Oura logs the owner in and
 *    returns the owner's code with the attacker's `state`. GUARD: the callback
 *    only completes in the browser that approved, because the cookie must
 *    match the `state`.
 *
 * And one rule under all three: THIS DEPLOYMENT HAS ONE OWNER. After Oura's
 * login the account's email is read and compared to `OURA_OWNER_EMAIL`. If
 * that setting is missing, nothing works — failing open would turn a personal
 * connector into a public one.
 */

import type { AuthRequest } from "@cloudflare/workers-oauth-provider";

import { AUTHORIZE_URL, SCOPES, REVOKE_URL, fromResponse, post,
         normalizeScopes } from "../../src/credentials.js";
import { OuraError } from "../../src/client.js";
import { type Env, sandbox, tokens } from "./env.js";
import { consentPage, messagePage } from "./pages.js";

const COOKIE = "__Host-oura_consent";
const PENDING_TTL = 600;                                   // seconds
const PERSONAL_INFO = "https://api.ouraring.com/v2/usercollection/personal_info";

interface Pending {
  req: AuthRequest;
  clientName: string;
}

/** What the grant carries. Deliberately nothing secret: tokens live in `OuraTokens`. */
export interface Props {
  identity: string;
}

/** Everything that must be set before anyone is let in, or undefined if it all is. */
export function missingConfig(env: Env): string[] {
  const missing: string[] = [];
  if (!(env.OURA_TIMEZONE ?? "").trim()) missing.push("OURA_TIMEZONE");
  if (sandbox(env)) return missing;
  for (const k of ["OURA_CLIENT_ID", "OURA_CLIENT_SECRET", "OURA_OWNER_EMAIL"] as const) {
    if (!(env[k] ?? "").trim()) missing.push(k);
  }
  return missing;
}

function cookieOf(request: Request): string | undefined {
  for (const part of (request.headers.get("cookie") ?? "").split(/;\s*/)) {
    const i = part.indexOf("=");
    if (i > 0 && part.slice(0, i) === COOKIE) return part.slice(i + 1);
  }
  return undefined;
}

const setCookie = (value: string, maxAge: number) =>
  `${COOKIE}=${value}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=${maxAge}`;

function nonce(): string {
  const b = new Uint8Array(32);
  crypto.getRandomValues(b);
  return [...b].map((x) => x.toString(16).padStart(2, "0")).join("");
}

/** Constant-time, so a cookie cannot be guessed one character at a time. */
function same(a: string | undefined, b: string | undefined): boolean {
  if (!a || !b || a.length !== b.length) return false;
  let d = 0;
  for (let i = 0; i < a.length; i++) d |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return d === 0;
}

function redirect(to: string, cookie?: string): Response {
  const h = new Headers({ location: to, "cache-control": "no-store" });
  if (cookie) h.append("set-cookie", cookie);
  return new Response(null, { status: 302, headers: h });
}

/** GET /authorize — validate the request, and show the owner who is asking. */
export async function showConsent(request: Request, env: Env): Promise<Response> {
  const missing = missingConfig(env);
  if (missing.length) {
    return messagePage(500, "Not configured yet",
      `This connector refuses to run until these are set: ${missing.join(", ")}. ` +
      `See the deployment instructions.`);
  }
  let req: AuthRequest;
  try {
    req = await env.OAUTH_PROVIDER.parseAuthRequest(request);
  } catch (e) {
    // Rendered here and never redirected: an invalid redirect URI is exactly
    // the one place a redirect must not go.
    return messagePage(400, "This request is not valid", (e as Error).message);
  }
  const client = await env.OAUTH_PROVIDER.lookupClient(req.clientId);
  if (!client) return messagePage(400, "Unknown client", "No such OAuth client is registered.");

  const n = nonce();
  const clientName = client.clientName || req.clientId;
  await env.OAUTH_KV.put(`oura_pending:${n}`,
                         JSON.stringify({ req, clientName } satisfies Pending),
                         { expirationTtl: PENDING_TTL });
  return consentPage({ nonce: n, clientName, redirectUri: req.redirectUri,
                       sandbox: sandbox(env), cookie: setCookie(n, PENDING_TTL) });
}

/** POST /authorize — the owner clicked. Only now does anyone go to Oura. */
export async function approve(request: Request, env: Env): Promise<Response> {
  const url = new URL(request.url);
  // Guard 2. A browser always sends Origin on a POST; a missing one is not a
  // browser we are willing to trust with this.
  if (request.headers.get("origin") !== url.origin) {
    return messagePage(403, "Refused", "This approval did not come from this page.");
  }
  const form = await request.formData();
  const n = String(form.get("nonce") ?? "");
  if (!same(n, cookieOf(request))) {
    return messagePage(403, "Refused",
      "This approval is not tied to the page you were shown. Start again from the app.");
  }
  const pending = await env.OAUTH_KV.get<Pending>(`oura_pending:${n}`, "json");
  if (!pending) {
    return messagePage(400, "Expired", "That request expired. Start again from the app.");
  }

  if (form.get("decision") !== "approve") {
    await env.OAUTH_KV.delete(`oura_pending:${n}`);
    const back = new URL(pending.req.redirectUri);
    back.searchParams.set("error", "access_denied");
    if (pending.req.state) back.searchParams.set("state", pending.req.state);
    return redirect(back.toString(), setCookie("", 0));
  }

  if (sandbox(env)) {
    // Sample data only: there is no Oura account to sign in to, and nothing of
    // anyone's to protect. The consent screen above still ran.
    await env.OAUTH_KV.delete(`oura_pending:${n}`);
    return complete(env, pending, "sandbox");
  }

  const oura = new URL(AUTHORIZE_URL);
  oura.searchParams.set("response_type", "code");
  oura.searchParams.set("client_id", env.OURA_CLIENT_ID);
  oura.searchParams.set("redirect_uri", callbackUrl(url.origin));
  oura.searchParams.set("scope", SCOPES.join(" "));
  oura.searchParams.set("state", n);
  return redirect(oura.toString());
}

/**
 * The redirect URI to register in Oura's portal. The TRAILING SLASH IS NOT
 * STYLE: Oura rejects `…/callback` with `invalid_redirect_uri` and accepts
 * `…/callback/`, the same as on stdio.
 */
export const callbackUrl = (origin: string) => `${origin}/callback/`;

/** GET /callback/ — Oura sent the owner back. Check who they are, then finish. */
export async function callback(request: Request, env: Env): Promise<Response> {
  const url = new URL(request.url);
  const error = url.searchParams.get("error");
  if (error) return messagePage(400, "Oura did not authorize", error);

  const state = url.searchParams.get("state") ?? "";
  const code = url.searchParams.get("code") ?? "";
  // Guard 3.
  if (!same(state, cookieOf(request))) {
    return messagePage(403, "Refused",
      "This sign-in did not start in this browser. Start again from the app.");
  }
  const pending = await env.OAUTH_KV.get<Pending>(`oura_pending:${state}`, "json");
  if (!pending || !code) {
    return messagePage(400, "Expired", "That sign-in expired. Start again from the app.");
  }
  await env.OAUTH_KV.delete(`oura_pending:${state}`);       // one use

  let cred;
  try {
    cred = fromResponse(await post({
      grant_type: "authorization_code",
      code,
      redirect_uri: callbackUrl(url.origin),
      client_id: env.OURA_CLIENT_ID,
      client_secret: env.OURA_CLIENT_SECRET,
    }));
  } catch (e) {
    return messagePage(502, "Oura refused the code", (e as Error).message);
  }

  const email = await ownerEmail(cred.access.reveal());
  if (!email) {
    return messagePage(403, "Cannot confirm who you are",
      "This connector checks the Oura account's email against its owner's, and " +
      "Oura returned none. Sign in again and keep the «email» permission.");
  }
  if (email !== env.OURA_OWNER_EMAIL.trim().toLowerCase()) {
    // Not stored, and handed back: a stranger's session has no business here.
    await revoke(cred.access.reveal());
    return messagePage(403, "Not this connector's owner",
      "This connector belongs to a different Oura account. Deploy your own — " +
      "it takes a few minutes and your data never passes through anyone else.");
  }

  await tokens(env).store({
    access: cred.access.reveal(),
    refresh: cred.refreshToken?.reveal() ?? null,
    expiresAt: cred.expiresAt,
    scopes: normalizeScopes(cred.scopes),
  });
  return complete(env, pending, "owner");
}

async function complete(env: Env, pending: Pending, identity: string): Promise<Response> {
  const { redirectTo } = await env.OAUTH_PROVIDER.completeAuthorization({
    request: pending.req,
    userId: identity,
    metadata: { clientName: pending.clientName },
    scope: pending.req.scope,
    props: { identity } satisfies Props,
  });
  return redirect(redirectTo, setCookie("", 0));
}

/** Lower-cased, or undefined if Oura withheld it. Only the email is read. */
async function ownerEmail(access: string): Promise<string | undefined> {
  const r = await fetch(PERSONAL_INFO, { headers: { authorization: `Bearer ${access}` } });
  if (!r.ok) return undefined;
  const body = await r.json().catch(() => ({})) as { email?: unknown };
  return typeof body.email === "string" && body.email.trim()
    ? body.email.trim().toLowerCase() : undefined;
}

async function revoke(access: string): Promise<void> {
  try {
    await fetch(`${REVOKE_URL}?access_token=${encodeURIComponent(access)}`);
  } catch { /* best effort: it was never stored either way */ }
}

export { OuraError };
