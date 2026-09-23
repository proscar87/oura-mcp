/**
 * The owner's Oura tokens, and the ONLY place they are ever refreshed.
 *
 * WHY A DURABLE OBJECT AND NOT THE GRANT'S PROPS. The OAuth provider can keep
 * upstream tokens inside each grant and refresh them from its token-exchange
 * hook, and that is what its examples do. Here it would lock the owner out.
 * Oura's refresh token is SINGLE-USE: the grant lives in KV, KV has no
 * transactions, and two refreshes landing together — claude.ai and ChatGPT
 * both connected, or one client retrying — would both read the same Oura
 * refresh token, and the second exchange would kill the session the first had
 * just renewed. That is the exact failure `credentials.test.ts` exists to keep
 * out of the stdio server, reintroduced by storage.
 *
 * One object, addressed by a fixed name, means one owner and one place. The
 * shared promise below makes refreshes inside it strictly one at a time: a
 * Durable Object serializes storage, but NOT outbound fetches, so without it
 * two requests could still both reach Oura's token endpoint.
 *
 * It also decouples the two OAuth layers. Every MCP client that connects —
 * claude.ai, ChatGPT, both — gets its own grant from this Worker, and they all
 * read the one Oura session kept here.
 */

import { DurableObject } from "cloudflare:workers";

import { fromResponse, post, normalizeScopes } from "../../src/credentials.js";
import { OuraError } from "../../src/client.js";
import type { Env } from "./env.js";

/** What is kept. Tokens only: no health data is ever written here. */
export interface Stored {
  access: string;
  refresh: string | null;
  expiresAt: number;             // epoch ms
  scopes: string[];
}

/** Same margin as the stdio server: a token about to expire already has. */
const MARGIN = 60_000;

export class OuraTokens extends DurableObject<Env> {
  private inFlight: Promise<Stored> | undefined;

  /** Replaces the session. Called once per completed Oura login. */
  async store(s: Stored): Promise<void> {
    await this.ctx.storage.put("tokens", s);
  }

  async scopes(): Promise<string[] | undefined> {
    return (await this.ctx.storage.get<Stored>("tokens"))?.scopes;
  }

  /** A valid Oura access token, refreshing it first if it needs to be. */
  async accessToken(): Promise<string> {
    const s = await this.ctx.storage.get<Stored>("tokens");
    if (!s) {
      throw new OuraError(
        "this connector has no Oura session. Disconnect and reconnect it, and " +
        "sign in to Oura when asked.");
    }
    if (Date.now() + MARGIN < s.expiresAt) return s.access;
    this.inFlight ??= this.refreshOnce(s).finally(() => { this.inFlight = undefined; });
    return (await this.inFlight).access;
  }

  async forget(): Promise<void> {
    await this.ctx.storage.deleteAll();
  }

  private async refreshOnce(s: Stored): Promise<Stored> {
    if (!s.refresh) {
      throw new OuraError(
        "Oura gave this connector no refresh token, so it cannot renew itself. " +
        "Disconnect and reconnect it.");
    }
    const r = await post({
      grant_type: "refresh_token",
      refresh_token: s.refresh,
      client_id: this.env.OURA_CLIENT_ID,
      client_secret: this.env.OURA_CLIENT_SECRET,
    });
    const c = fromResponse(r, s.scopes);
    const next: Stored = {
      access: c.access.reveal(),
      refresh: c.refreshToken?.reveal() ?? null,
      expiresAt: c.expiresAt,
      scopes: normalizeScopes(c.scopes),
    };
    // BEFORE returning, exactly as on stdio. The moment the request above went
    // out, the refresh token we held died.
    await this.ctx.storage.put("tokens", next);
    return next;
  }
}
