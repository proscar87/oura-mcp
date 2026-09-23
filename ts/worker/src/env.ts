import type { OAuthHelpers } from "@cloudflare/workers-oauth-provider";

export interface Env {
  OAUTH_KV: KVNamespace;
  OAUTH_PROVIDER: OAuthHelpers;
  OURA_TOKENS: DurableObjectNamespace<import("./tokens.js").OuraTokens>;

  // Secrets, via `wrangler secret put`. Never in wrangler.jsonc.
  OURA_CLIENT_ID: string;
  OURA_CLIENT_SECRET: string;
  /** The Oura account allowed in. Anyone else who signs in is turned away. */
  OURA_OWNER_EMAIL: string;

  // Plain vars.
  OURA_TIMEZONE: string;
  OURA_SANDBOX?: string;
}

export const sandbox = (env: Env): boolean =>
  ["1", "true", "yes", "on"].includes((env.OURA_SANDBOX ?? "").trim().toLowerCase());

/** The one Oura session this deployment serves. */
export const tokens = (env: Env) =>
  env.OURA_TOKENS.get(env.OURA_TOKENS.idFromName("owner"));
