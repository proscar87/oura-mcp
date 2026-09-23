/**
 * The owner's Oura session: refreshed in exactly one place, one at a time.
 *
 * Oura's refresh token is single-use. Two refreshes of the same token — two
 * connected clients whose requests land together — and the second kills the
 * session the first just renewed. The Durable Object serializes storage but
 * not outbound fetches, so the guard is ours to test.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { OuraTokens, type Stored } from "../src/tokens.js";
import { resetTokenUrl } from "../../src/credentials.js";

let mem: Map<string, unknown>;
let exchanges: string[];

function object(): OuraTokens {
  const ctx = {
    storage: {
      get: async (k: string) => mem.get(k),
      put: async (k: string, v: unknown) => { mem.set(k, structuredClone(v)); },
      deleteAll: async () => { mem.clear(); },
    },
  };
  return new OuraTokens(ctx as never, { OURA_CLIENT_ID: "id", OURA_CLIENT_SECRET: "s" } as never);
}

const expired = (refresh: string): Stored =>
  ({ access: "old", refresh, expiresAt: Date.now() - 1000, scopes: ["daily"] });

beforeEach(() => {
  mem = new Map();
  exchanges = [];
  resetTokenUrl();
  vi.stubGlobal("fetch", async (_url: string, init?: RequestInit) => {
    const body = new URLSearchParams(String(init?.body));
    const used = body.get("refresh_token")!;
    exchanges.push(used);
    await new Promise((r) => setTimeout(r, 20));        // Oura is not instant
    if (exchanges.filter((x) => x === used).length > 1) {
      return Response.json({ error: "invalid_grant", error_description: "Refresh token already used" },
                           { status: 400 });
    }
    return Response.json({ access_token: `A-${exchanges.length}`, refresh_token: `R-${exchanges.length}`,
                           expires_in: 86400, scope: "extapi:daily extapi:heartrate" });
  });
});
afterEach(() => vi.unstubAllGlobals());

describe("OuraTokens", () => {
  it("hands back a valid token without touching Oura", async () => {
    mem.set("tokens", { access: "live", refresh: "R0", expiresAt: Date.now() + 3_600_000,
                        scopes: ["daily"] });
    expect(await object().accessToken()).toBe("live");
    expect(exchanges).toEqual([]);
  });

  it("refreshes an expired one ONCE, however many ask at the same moment", async () => {
    mem.set("tokens", expired("R0"));
    const o = object();
    const got = await Promise.all([o.accessToken(), o.accessToken(), o.accessToken()]);
    expect(exchanges).toEqual(["R0"]);
    expect(new Set(got)).toEqual(new Set(["A-1"]));
  });

  it("stores the new pair before anyone gets the token, scopes named plainly", async () => {
    mem.set("tokens", expired("R0"));
    await object().accessToken();
    const s = mem.get("tokens") as Stored;
    expect(s.refresh).toBe("R-1");
    expect(s.scopes).toEqual(["daily", "heartrate"]);
  });

  it("says to reconnect when there is no session at all", async () => {
    await expect(object().accessToken()).rejects.toThrow(/reconnect/);
  });
});
