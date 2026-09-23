/**
 * The Oura half of the front door — the half `wrangler dev` in sandbox mode
 * cannot reach, because sandbox skips Oura's login. Oura, KV, the OAuth
 * provider and the token store are fakes; the code under test is real.
 *
 * The sandbox run already exercised, against the real provider in workerd:
 * registration, the consent page, the three forged approvals (no Origin, a
 * foreign Origin, no cookie), a replayed approval, the token exchange and the
 * MCP endpoint. What is left is what only a real Oura account would show.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { approve, callback, showConsent, callbackUrl } from "../src/authorize.js";
import type { Env } from "../src/env.js";
import type { Stored } from "../src/tokens.js";

const ORIGIN = "https://oura-mcp.owner.workers.dev";
const NONCE = "n".repeat(64);
const REQ = { clientId: "c1", redirectUri: "https://claude.ai/api/mcp/auth_callback",
              scope: [], state: "client-state", responseType: "code" };

let kv: Map<string, string>;
let stored: Stored | undefined;
let completed: Record<string, unknown> | undefined;
let calls: string[];

function env(over: Partial<Env> = {}): Env {
  return {
    OAUTH_KV: {
      get: async (k: string, t?: string) => {
        const v = kv.get(k);
        return v === undefined ? null : t === "json" ? JSON.parse(v) : v;
      },
      put: async (k: string, v: string) => { kv.set(k, v); },
      delete: async (k: string) => { kv.delete(k); },
    } as unknown as KVNamespace,
    OAUTH_PROVIDER: {
      parseAuthRequest: async () => REQ,
      lookupClient: async () => ({ clientName: "Claude" }),
      completeAuthorization: async (o: Record<string, unknown>) => {
        completed = o;
        return { redirectTo: `${REQ.redirectUri}?code=mcp-code` };
      },
    } as never,
    OURA_TOKENS: {
      idFromName: () => "id",
      get: () => ({ store: async (s: Stored) => { stored = s; } }),
    } as never,
    OURA_CLIENT_ID: "oura-client",
    OURA_CLIENT_SECRET: "oura-secret",
    OURA_OWNER_EMAIL: "Owner@Example.com",
    OURA_TIMEZONE: "America/Mexico_City",
    ...over,
  };
}

/** Oura: the token endpoint and personal_info, answering as `email`. */
function fakeOura(email: string | undefined, scope = "extapi:email extapi:daily extapi:personal") {
  vi.stubGlobal("fetch", async (url: string) => {
    calls.push(String(url).split("?")[0]!);
    if (String(url).includes("oauth/token")) {
      return Response.json({ access_token: "OA", refresh_token: "OR", expires_in: 86400, scope });
    }
    if (String(url).includes("personal_info")) {
      return Response.json(email === undefined ? { age: 40 } : { email });
    }
    return new Response("", { status: 200 });          // revoke
  });
}

const withCookie = (v: string) => ({ cookie: `other=1; __Host-oura_consent=${v}` });

function cb(state: string, cookie = state) {
  return new Request(`${ORIGIN}/callback/?code=oura-code&state=${state}`,
                     { headers: withCookie(cookie) });
}

beforeEach(() => {
  kv = new Map([[`oura_pending:${NONCE}`, JSON.stringify({ req: REQ, clientName: "Claude" })]]);
  stored = undefined;
  completed = undefined;
  calls = [];
});
afterEach(() => vi.unstubAllGlobals());

describe("the deployment refuses to run half-configured", () => {
  it("without an owner, lets nobody in", async () => {
    // Failing open here turns a personal connector into a public one.
    const r = await showConsent(new Request(`${ORIGIN}/authorize`), env({ OURA_OWNER_EMAIL: "" }));
    expect(r.status).toBe(500);
    expect(await r.text()).toContain("OURA_OWNER_EMAIL");
  });

  it("without a time zone, too", async () => {
    const r = await showConsent(new Request(`${ORIGIN}/authorize`), env({ OURA_TIMEZONE: "" }));
    expect(r.status).toBe(500);
    expect(await r.text()).toContain("OURA_TIMEZONE");
  });
});

describe("approving", () => {
  const post = (decision: string) => new Request(`${ORIGIN}/authorize`, {
    method: "POST",
    headers: { origin: ORIGIN, "content-type": "application/x-www-form-urlencoded",
               ...withCookie(NONCE) },
    body: `nonce=${NONCE}&decision=${decision}`,
  });

  it("sends the owner to Oura only after the click, with the slash Oura requires", async () => {
    const r = await approve(post("approve"), env());
    expect(r.status).toBe(302);
    const to = new URL(r.headers.get("location")!);
    expect(to.origin + to.pathname).toBe("https://cloud.ouraring.com/oauth/authorize");
    expect(to.searchParams.get("redirect_uri")).toBe(`${ORIGIN}/callback/`);
    expect(to.searchParams.get("state")).toBe(NONCE);
    expect(to.searchParams.get("client_id")).toBe("oura-client");
    expect(callbackUrl(ORIGIN).endsWith("/")).toBe(true);
  });

  it("a denial goes back to the client as access_denied, and forgets the request", async () => {
    const r = await approve(post("deny"), env());
    const to = new URL(r.headers.get("location")!);
    expect(to.searchParams.get("error")).toBe("access_denied");
    expect(to.searchParams.get("state")).toBe("client-state");
    expect(kv.has(`oura_pending:${NONCE}`)).toBe(false);
  });
});

describe("Oura's callback", () => {
  it("completes only in the browser that approved", async () => {
    // Guard 3: the attacker's own approved `state`, delivered to the owner.
    fakeOura("owner@example.com");
    const r = await callback(cb(NONCE, "a-different-cookie"), env());
    expect(r.status).toBe(403);
    expect(calls).toEqual([]);                 // Oura was never even asked
    expect(completed).toBeUndefined();
  });

  it("turns away an Oura account that is not the owner, and keeps nothing", async () => {
    fakeOura("stranger@example.com");
    const r = await callback(cb(NONCE), env());
    expect(r.status).toBe(403);
    expect(stored).toBeUndefined();
    expect(completed).toBeUndefined();
    expect(calls).toContain("https://api.ouraring.com/oauth/revoke");
  });

  it("refuses when Oura withholds the email it would be checked against", async () => {
    fakeOura(undefined);
    const r = await callback(cb(NONCE), env());
    expect(r.status).toBe(403);
    expect(stored).toBeUndefined();
  });

  it("lets the owner in, case-insensitively, with the scopes named plainly", async () => {
    // Oura grants `extapi:`-prefixed scopes now; the 0.3.6 bug, not repeated here.
    fakeOura("OWNER@example.com");
    const r = await callback(cb(NONCE), env());
    expect(r.status).toBe(302);
    expect(r.headers.get("location")).toContain("mcp-code");
    expect(stored?.access).toBe("OA");
    expect(stored?.refresh).toBe("OR");
    expect(stored?.scopes).toEqual(["email", "daily", "personal"]);
    expect(completed?.["props"]).toEqual({ identity: "owner" });
  });

  it("is single-use", async () => {
    fakeOura("owner@example.com");
    await callback(cb(NONCE), env());
    const again = await callback(cb(NONCE), env());
    expect(again.status).toBe(400);
  });
});
