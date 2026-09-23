/**
 * The `oura_compare` wrapper in the half that ships in the `.mcpb` and the
 * Worker. The method is held to Python's by the parity test; this is what sits
 * around it — today left out, an incomplete fetch refused, the grant passed on.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Secret, cacheClear, type Auth } from "../src/client.js";
import { compare } from "../src/server.js";

let asked: string[];

function ouraWith(body: Record<string, unknown>) {
  vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
    asked.push(`${new Headers(init?.headers).get("authorization")} ${url}`);
    return new Response(JSON.stringify(body), { status: 200 });
  });
}

const Q = { metric: "daily_activity.steps", a_start: "2026-03-01", a_end: "2026-03-14",
            b_start: "2026-03-18", b_end: "2026-03-31" };

beforeEach(() => {
  asked = [];
  process.env.OURA_PAT = "t";
  delete process.env.OURA_SANDBOX;
  cacheClear();
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-03-31T18:00:00"));
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("oura_compare", () => {
  it("leaves today out, says so, and asks Oura only up to yesterday", async () => {
    ouraWith({ data: [] });
    const r = await compare(Q);
    expect((r["period_b"] as Record<string, unknown>)["end"]).toBe("2026-03-30");
    expect(r["excluded"]).toHaveProperty("today");
    expect(asked[0]).toContain("fields=steps");
    expect(r["verdict"]).toBe("cannot_tell");
  });

  it("refuses an incomplete answer instead of computing on part of it", async () => {
    ouraWith({ data: [{ day: "2026-03-02", steps: 1 }], next_token: "same" });
    const r = await compare(Q);
    expect(String(r["error"])).toContain("incomplete");
  });

  it("asks Oura with the grant it was handed", async () => {
    ouraWith({ data: [] });
    const auth: Auth = { identity: "ana", token: async () => new Secret("ana-token") };
    await compare(Q, auth);
    expect(asked[0]).toMatch(/^Bearer ana-token /);
  });

  it("refuses a collection with many records a day", async () => {
    const r = await compare({ ...Q, metric: "heartrate.bpm" });
    expect(String(r["error"])).toContain("one record per day");
  });
});
