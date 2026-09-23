/**
 * oura-mcp as a remote MCP server, for claude.ai, ChatGPT and anything else
 * that connects to an MCP server by URL.
 *
 * DEPLOYED BY EACH PERSON, ON THEIR OWN CLOUDFLARE ACCOUNT, for their own Oura
 * account only. Nobody operates a shared instance, so nobody holds anyone
 * else's health data — which is the reason the hosted connector stayed off the
 * roadmap.
 *
 * Two OAuth layers, deliberately separate:
 *
 *   MCP client ──OAuth──▶ this Worker ──OAuth──▶ Oura
 *
 * The provider issues and checks the first layer's tokens. `authorize.ts` runs
 * the consent screen and Oura's login. `OuraTokens` keeps the second layer's
 * tokens and is the only thing that refreshes them.
 */

import { OAuthProvider } from "@cloudflare/workers-oauth-provider";

import { approve, callback, showConsent } from "./authorize.js";
import { handleMcp } from "./mcp.js";
import { messagePage } from "./pages.js";
import type { Env } from "./env.js";

export { OuraTokens } from "./tokens.js";

const defaultHandler = {
  async fetch(request: Request, env: Env): Promise<Response> {
    const { pathname } = new URL(request.url);
    if (pathname === "/authorize") {
      if (request.method === "GET") return showConsent(request, env);
      if (request.method === "POST") return approve(request, env);
    }
    if (pathname === "/callback/" && request.method === "GET") return callback(request, env);
    if (pathname === "/") {
      return messagePage(200, "oura-mcp",
        "A personal Oura connector. Add this address followed by /mcp as a custom " +
        "connector in claude.ai or ChatGPT.");
    }
    return messagePage(404, "Not found", "Nothing here.");
  },
};

export default new OAuthProvider<Env>({
  apiRoute: "/mcp",
  apiHandler: { fetch: handleMcp as never },
  defaultHandler: defaultHandler as never,
  authorizeEndpoint: "/authorize",
  tokenEndpoint: "/token",
  // Both registration routes MCP clients use today. CIMD is the one the
  // 2026-07-28 spec prefers; DCR stays for clients that have not moved.
  clientIdMetadataDocumentEnabled: true,
  clientRegistrationEndpoint: "/register",
});
