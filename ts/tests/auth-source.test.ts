/**
 * The core, run the way the remote Worker runs it.
 *
 * ONE PROCESS, MANY REQUESTS. Over stdio a server is one process per person
 * and module state is that person's. A Worker isolate serves request after
 * request, and three pieces of module state quietly assumed otherwise:
 *
 * - the cache was keyed by collection and range, not by whose data it was;
 * - the token came from env vars and a file on this machine;
 * - «today» was the process's local day, and a Worker's clock is UTC.
 *
 * Each test here fails on the code before `Auth` existed. None touches the
 * network: `fetch` is replaced.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Secret, fetchAll, cacheClear, rangeHasClosed, today as localDay,
         type Auth } from "../src/client.js";
import { check } from "../src/server.js";

const seen: string[] = [];

/** Oura as seen by a Worker: the records depend on WHICH token asked. */
function ouraByToken() {
  vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
    const auth = new Headers(init?.headers).get("authorization") ?? "";
    seen.push(auth);
    const who = auth.replace(/^Bearer /, "");
    return new Response(JSON.stringify({
      data: [{ id: `${who}-1`, day: "2026-01-02", score: who === "ana" ? 91 : 55 }],
    }), { status: 200 });
  });
}

function auth(identity: string, scopes?: string[]): Auth {
  return { identity, token: async () => new Secret(identity), scopes };
}

beforeEach(() => {
  seen.length = 0;
  delete process.env.OURA_SANDBOX;
  delete process.env.OURA_PAT;
  delete process.env.OURA_PAT_FILE;
  delete process.env.OURA_TIMEZONE;
  cacheClear();
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  delete process.env.OURA_TIMEZONE;
});

describe("an injected token source", () => {
  it("is the token that reaches Oura, not the machine's", async () => {
    process.env.OURA_PAT = "the-machine-token";
    ouraByToken();
    await fetchAll("daily_sleep", { start: "2026-01-02", end: "2026-01-02",
                                    auth: auth("ana") });
    expect(seen).toEqual(["Bearer ana"]);
  });

  it("never serves one identity's held answer to another", async () => {
    // A closed range is held forever — that is the cache's whole rule — so the
    // second asker of the same range would be answered from memory with the
    // first asker's sleep. Over stdio there is only ever one asker. In a
    // Worker there need not be.
    ouraByToken();
    const q = { start: "2026-01-02", end: "2026-01-02" };
    const a = await fetchAll("daily_sleep", { ...q, auth: auth("ana") });
    const b = await fetchAll("daily_sleep", { ...q, auth: auth("beto") });
    expect((a["data"] as { id: string }[])[0]!.id).toBe("ana-1");
    expect((b["data"] as { id: string }[])[0]!.id).toBe("beto-1");
    expect(b["cached"]).toBeUndefined();
  });

  it("names a missing scope from the grant it was given", async () => {
    vi.stubGlobal("fetch", async () =>
      new Response(JSON.stringify({ data: [] }), { status: 200 }));
    const r = await fetchAll("workout", { start: "2026-01-01", end: "2026-01-05",
                                          auth: auth("ana", ["daily"]) });
    const why = JSON.stringify((r["empty"] as Record<string, unknown>)["what_we_know"]);
    expect(why).toContain("`workout` scope");
    // Not `oura-mcp --authorize`: whoever reads this is in a browser tab of
    // claude.ai or ChatGPT, where no such command exists.
    expect(why).not.toContain("--authorize");
    expect(why).toContain("reconnect");
  });

  it("says nothing about scopes when the grant carries none", async () => {
    vi.stubGlobal("fetch", async () =>
      new Response(JSON.stringify({ data: [] }), { status: 200 }));
    const r = await fetchAll("workout", { start: "2026-01-01", end: "2026-01-05",
                                          auth: auth("ana") });
    expect(JSON.stringify(r["empty"])).not.toContain("scope");
  });

  it("drives the self-check from the grant, not from local files", async () => {
    ouraByToken();
    const r = await check(auth("ana", ["daily", "personal"]));
    expect(r["token_present"]).toBe(true);
    expect(r["granted_scopes"]).toEqual(["daily", "personal"]);
    expect(r["ungranted_scopes"]).toContain("workout");
    expect(String(r["mode"])).toMatch(/remote/);
  });
});

describe("the day, when the clock is not the person's", () => {
  it("follows OURA_TIMEZONE rather than the process's zone", () => {
    // A Worker's clock is UTC; without this, the person's «today» reads as a
    // closed day and is held forever the moment it is first asked for. Two
    // zones either side of UTC, so the test means the same on any machine.
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-01-02T20:00:00Z"));
    process.env.OURA_TIMEZONE = "Asia/Tokyo";          // already 05:00 on the 3rd
    expect(localDay()).toBe("2026-01-03");
    expect(rangeHasClosed("2026-01-02")).toBe(true);
    process.env.OURA_TIMEZONE = "Pacific/Honolulu";    // still 10:00 on the 2nd
    expect(localDay()).toBe("2026-01-02");
    expect(rangeHasClosed("2026-01-02")).toBe(false);
  });

  it("refuses a zone that does not exist instead of guessing one", () => {
    process.env.OURA_TIMEZONE = "America/Atlantis";
    expect(() => localDay()).toThrow(/OURA_TIMEZONE/);
  });
});
