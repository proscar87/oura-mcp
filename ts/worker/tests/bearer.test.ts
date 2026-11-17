/**
 * The optional fixed bearer token — the door for apps that cannot do OAuth.
 *
 * Driven through the Worker's own `fetch`, with the real OAuth provider in
 * front, because the thing worth proving is not that two strings compare but
 * that the provider asks, and that a wrong answer is still a 401. KV and the
 * token store are fakes; sandbox mode keeps Oura out of it.
 *
 * Every token here is made up for the test. None is, or resembles, a real one.
 */

import { describe, expect, it } from "vitest";

import worker from "../src/index.js";
import { MIN_BEARER_LENGTH, configuredBearer, matchesBearer,
         resolveStaticBearer } from "../src/bearer.js";
import type { Env } from "../src/env.js";

const ORIGIN = "https://oura-mcp.owner.workers.dev";
const SECRET = "test-only-fixed-bearer-0123456789abcdef-XYZ";   // 43 chars
const INIT = { jsonrpc: "2.0", id: 1, method: "initialize",
               params: { protocolVersion: "2025-06-18", capabilities: {},
                         clientInfo: { name: "bearer-test", version: "1" } } };

function env(over: Partial<Env> = {}): Env {
  const kv = new Map<string, string>();
  return {
    OAUTH_KV: {
      get: async (k: string) => kv.get(k) ?? null,
      put: async (k: string, v: string) => { kv.set(k, v); },
      delete: async (k: string) => { kv.delete(k); },
      list: async () => ({ keys: [], list_complete: true }),
    } as unknown as KVNamespace,
    OURA_TOKENS: {
      idFromName: () => "id",
      get: () => ({ scopes: async () => ["daily"], accessToken: async () => "OA" }),
    } as never,
    OURA_CLIENT_ID: "oura-client",
    OURA_CLIENT_SECRET: "oura-secret",
    OURA_OWNER_EMAIL: "owner@example.com",
    OURA_TIMEZONE: "America/Mexico_City",
    OURA_SANDBOX: "1",
    ...over,
  } as Env;
}

const ctx = () => ({ waitUntil() {}, passThroughOnException() {}, props: undefined }) as never;

function mcp(e: Env, authorization?: string): Promise<Response> {
  const headers: Record<string, string> = {
    "content-type": "application/json",
    accept: "application/json, text/event-stream",
  };
  if (authorization !== undefined) headers.authorization = authorization;
  return (worker as unknown as { fetch: (r: Request, e: Env, c: never) => Promise<Response> })
    .fetch(new Request(`${ORIGIN}/mcp`, { method: "POST", headers, body: JSON.stringify(INIT) }),
           e, ctx());
}

describe("the fixed bearer token, through the Worker", () => {
  it("lets the right token in, and the MCP endpoint answers", async () => {
    const r = await mcp(env({ MCP_BEARER_TOKEN: SECRET }), `Bearer ${SECRET}`);
    expect(r.status).toBe(200);
    expect(JSON.stringify(await r.json())).toContain('"name":"oura"');
  });

  it("a secret stored with a trailing newline still matches", async () => {
    const r = await mcp(env({ MCP_BEARER_TOKEN: `${SECRET}\n` }), `Bearer ${SECRET}`);
    expect(r.status).toBe(200);
  });

  it.each([
    ["one character off, same length", `${SECRET.slice(0, -1)}Q`],
    ["a prefix of the secret", SECRET.slice(0, 40)],
    ["the secret with more after it", `${SECRET}x`],
    ["another case", SECRET.toUpperCase()],
    ["shaped like one of the provider's own tokens", "owner:grant:secret"],
  ])("refuses %s", async (_name, token) => {
    const r = await mcp(env({ MCP_BEARER_TOKEN: SECRET }), `Bearer ${token}`);
    expect(r.status).toBe(401);
    expect(r.headers.get("www-authenticate")).toContain("resource_metadata=");
  });

  it("is off when the secret is not set: the very token that would work is refused", async () => {
    const r = await mcp(env(), `Bearer ${SECRET}`);
    expect(r.status).toBe(401);
  });

  it.each([
    ["empty", ""],
    ["blank", "   "],
    ["one short of the minimum", "a".repeat(MIN_BEARER_LENGTH - 1)],
  ])("is off when the secret is %s, even for a token equal to it", async (_name, secret) => {
    const e = env({ MCP_BEARER_TOKEN: secret });
    expect((await mcp(e, `Bearer ${secret}`)).status).toBe(401);
    expect((await mcp(e, `Bearer ${secret.trim()}`)).status).toBe(401);
    expect((await mcp(e, "Bearer ")).status).toBe(401);
  });

  it("no Authorization header is still the OAuth challenge, with the mode on", async () => {
    const r = await mcp(env({ MCP_BEARER_TOKEN: SECRET }));
    expect(r.status).toBe(401);
    expect(r.headers.get("www-authenticate")).toContain("resource_metadata=");
  });

  it("is read from the Authorization header only", async () => {
    const e = env({ MCP_BEARER_TOKEN: SECRET });
    expect((await mcp(e, `Basic ${SECRET}`)).status).toBe(401);
    expect((await mcp(e, SECRET)).status).toBe(401);
    const r = await (worker as unknown as { fetch: (r: Request, e: Env, c: never) => Promise<Response> })
      .fetch(new Request(`${ORIGIN}/mcp?token=${SECRET}&access_token=${SECRET}`,
                         { method: "POST", body: JSON.stringify(INIT) }), e, ctx());
    expect(r.status).toBe(401);
  });

  it("opens the MCP endpoint and nothing else: the OAuth routes are as they were", async () => {
    const e = env({ MCP_BEARER_TOKEN: SECRET });
    const f = (worker as unknown as { fetch: (r: Request, e: Env, c: never) => Promise<Response> }).fetch
      .bind(worker);
    const meta = await f(new Request(`${ORIGIN}/.well-known/oauth-authorization-server`), e, ctx());
    expect(meta.status).toBe(200);
    expect((await meta.json() as { registration_endpoint: string }).registration_endpoint)
      .toBe(`${ORIGIN}/register`);
    const reg = await f(new Request(`${ORIGIN}/register`, {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ client_name: "t", redirect_uris: ["https://claude.ai/cb"],
                             token_endpoint_auth_method: "none" }),
    }), e, ctx());
    expect(reg.status).toBe(201);
  });
});

describe("the hook itself", () => {
  it("gives the fixed token the identity an OAuth grant carries", async () => {
    expect(await resolveStaticBearer({ token: SECRET, env: env({ MCP_BEARER_TOKEN: SECRET, OURA_SANDBOX: "" }) }))
      .toEqual({ props: { identity: "owner" } });
    expect(await resolveStaticBearer({ token: SECRET, env: env({ MCP_BEARER_TOKEN: SECRET }) }))
      .toEqual({ props: { identity: "sandbox" } });
  });

  it("answers null, and never throws, on anything that is not the token", async () => {
    const on = env({ MCP_BEARER_TOKEN: SECRET });
    for (const token of ["", " ", "x", "ñ€\u0000", "a".repeat(100_000)]) {
      expect(await resolveStaticBearer({ token, env: on })).toBeNull();
      expect(await resolveStaticBearer({ token, env: env() })).toBeNull();
    }
    expect(await resolveStaticBearer(
      { token: SECRET, env: env({ MCP_BEARER_TOKEN: 42 as never }) })).toBeNull();
  });

  it("the minimum is on the secret, not on what is presented", () => {
    expect(configuredBearer(env({ MCP_BEARER_TOKEN: "a".repeat(MIN_BEARER_LENGTH) })))
      .toBe("a".repeat(MIN_BEARER_LENGTH));
    expect(configuredBearer(env({ MCP_BEARER_TOKEN: `  ${"a".repeat(MIN_BEARER_LENGTH - 1)}  ` })))
      .toBeUndefined();
    expect(MIN_BEARER_LENGTH).toBeGreaterThanOrEqual(32);
  });

  it("compares whole values, whatever their lengths", async () => {
    expect(await matchesBearer(SECRET, SECRET)).toBe(true);
    expect(await matchesBearer(SECRET.slice(0, -1), SECRET)).toBe(false);
    expect(await matchesBearer("", SECRET)).toBe(false);
  });

  it("compares every byte of the digests, not the first few or the last few", async () => {
    // A wrong guess almost never shares a digest byte with the secret, so a
    // comparison that stopped early would pass every test above. These are
    // found, not hoped for: guesses whose digest agrees with the secret's in
    // its first byte, and in its last.
    const sha = async (s: string) =>
      new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s)));
    const want = await sha(SECRET);
    let first: string | undefined, last: string | undefined;
    for (let i = 0; i < 100_000 && !(first && last); i++) {
      const guess = `guess-${i}`;
      const d = await sha(guess);
      if (d[0] === want[0]) first ??= guess;
      if (d[31] === want[31]) last ??= guess;
    }
    expect(first).toBeDefined();
    expect(last).toBeDefined();
    expect(await matchesBearer(first!, SECRET)).toBe(false);
    expect(await matchesBearer(last!, SECRET)).toBe(false);
  });
});
