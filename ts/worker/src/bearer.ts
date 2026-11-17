/**
 * The second way in: one fixed bearer token, for apps that cannot do OAuth.
 *
 * Some MCP clients — Meta's Muse and xAI's API at the time of writing — take a
 * URL and a single static token and nothing else. They can never reach the
 * consent page, so for them the OAuth front door is a wall.
 *
 * OFF UNLESS THE OWNER TURNS IT ON, by setting the secret `MCP_BEARER_TOKEN`.
 * Unset, blank, or shorter than `MIN_BEARER_LENGTH`, this file lets nobody in
 * and the Worker answers exactly as it did before it existed.
 *
 * WHAT IT IS NOT. It does not replace Oura's login, and it never creates an
 * Oura session: it reads the one the owner's OAuth login already left in
 * `OuraTokens`. It skips the consent page and the owner check because both
 * guard a redirect, and there is none here — the token is the whole proof.
 * That makes it a long-lived credential, which is why it is opt-in.
 *
 * Only the OAuth provider calls this, and only for a bearer token it did not
 * issue itself (`resolveExternalToken`). A token it issued never gets here.
 */

import { type Env, sandbox } from "./env.js";
import type { Props } from "./authorize.js";

/**
 * Shorter than this and the mode stays off. A guessable token would be the only
 * thing between the internet and someone's health data, and there is no login
 * behind it to fall back on. `openssl rand -base64 32` gives 44 characters.
 */
export const MIN_BEARER_LENGTH = 32;

/** The configured token, or undefined when the mode is off. */
export function configuredBearer(env: Env): string | undefined {
  const raw = env.MCP_BEARER_TOKEN;
  if (typeof raw !== "string") return undefined;
  // Trimmed: a secret piped in with `echo` carries a newline no header can.
  const secret = raw.trim();
  return secret.length >= MIN_BEARER_LENGTH ? secret : undefined;
}

const digest = async (s: string): Promise<Uint8Array> =>
  new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s)));

/**
 * Constant-time. Both sides are hashed first, so what is compared is always 32
 * bytes: neither the length of the secret nor how much of a guess was right
 * shows in the time taken. (`crypto.subtle.timingSafeEqual` exists only in
 * workerd; this runs the same under the Node test suite.)
 */
export async function matchesBearer(presented: string, secret: string): Promise<boolean> {
  const [a, b] = await Promise.all([digest(presented), digest(secret)]);
  let d = 0;
  for (let i = 0; i < a.length; i++) d |= a[i]! ^ b[i]!;
  return d === 0;
}

/**
 * The provider's `resolveExternalToken` hook. Returns the same props an OAuth
 * grant carries, so the cache and the token store see one owner whichever door
 * was used — or null, which the provider turns into its ordinary 401.
 *
 * Never throws: the provider re-throws what this does, and that would be a 500
 * where a 401 belongs.
 */
export async function resolveStaticBearer(
  { token, env }: { token: string; env: Env },
): Promise<{ props: Props } | null> {
  const secret = configuredBearer(env);
  if (!secret || !token) return null;
  if (!(await matchesBearer(token, secret))) return null;
  return { props: { identity: sandbox(env) ? "sandbox" : "owner" } };
}
