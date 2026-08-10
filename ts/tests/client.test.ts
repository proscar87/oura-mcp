/**
 * Client tests. THEY NEVER TOUCH THE NETWORK: `fetch` is replaced by a fake.
 *
 * What gets tested here are Oura's four silent failures and the three exits from
 * the pagination loop. A CI that needs someone's token to pass isn't a CI: it's
 * a dependency on that person.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  OuraError, Secret, toCsv, sizeWarning, ignoredFields, shiftDays, dayOf,
  requestedWait, detailOf, fetchAll,
} from "../src/client.js";

type Pagina = Record<string, unknown>[];

/** A fake API serving `pages`, each with its own next_token. */
function fakeOura(pages: Pagina[], registrar?: string[]) {
  vi.stubGlobal("fetch", async (url: string) => {
    registrar?.push(url);
    const m = /next_token=([^&]*)/.exec(url);
    const i = m ? Number(m[1]) : 0;
    const body: Record<string, unknown> = { data: pages[i] ?? [] };
    if (i + 1 < pages.length) body["next_token"] = String(i + 1);
    return new Response(JSON.stringify(body), { status: 200 });
  });
}

beforeEach(() => {
  process.env.OURA_PAT = "token-de-prueba";
  delete process.env.OURA_SANDBOX;
  delete process.env.OURA_PAT_FILE;
});
afterEach(() => vi.unstubAllGlobals());

// ── Pagination: the package's reason to exist ──────────────────────────────
describe("pagination", () => {
  it("follows next_token to the end", async () => {
    // THE SCAR THAT JUSTIFIES THE PACKAGE. Whoever doesn't chase the token gets
    // the first page with nothing saying so: valid JSON that looks complete.
    fakeOura(Array.from({ length: 5 }, () =>
      Array.from({ length: 100 }, (_, n) => ({ i: n }))));
    const r = await fetchAll("heartrate", {
      start: "2026-08-01T00:00:00Z", end: "2026-08-02T00:00:00Z" });
    expect(r["n"]).toBe(500);
    expect(r["pages"]).toBe(5);
    expect(r["truncated"]).toBeUndefined();
  });

  it("says so when truncating and leaves the cursor", async () => {
    fakeOura(Array.from({ length: 20 }, (_, n) => [{ i: n }]));
    const r = await fetchAll("heartrate", {
      start: "2026-08-01T00:00:00Z", end: "2026-08-02T00:00:00Z", pageLimit: 3 });
    expect(r["pages"]).toBe(3);
    expect(String(r["truncated"])).toContain("shorten");
    expect(r["continue_from"]).toBe("3");
  });

  it("detects a repeated next_token as a cycle, not as truncation", async () => {
    // Without this the client made 50 identical requests and the warning said
    // "shorten the range" — useless, since shortening doesn't stop the repeat.
    const llamadas: string[] = [];
    vi.stubGlobal("fetch", async (url: string) => {
      llamadas.push(url);
      return new Response(JSON.stringify({
        data: [{ day: "2026-08-01" }], next_token: "SIEMPRE-EL-MISMO" }), { status: 200 });
    });
    const r = await fetchAll("daily_sleep", { start: "2026-08-01", end: "2026-08-01" });
    expect(llamadas).toHaveLength(2);
    expect(r["pagination_cycle"]).toBeDefined();
    expect(r["truncated"]).toBeUndefined();
  });
});

// ── The date range: the second scar ───────────────────────────────────────
describe("date range", () => {
  it("requests two extra days on each side", async () => {
    // Not a courtesy margin: `workout` is exclusive AND skewed to UTC, and the
    // two stack. One day was not enough.
    const urls: string[] = [];
    fakeOura([[{}]], urls);
    await fetchAll("daily_sleep", { start: "2026-08-10", end: "2026-08-20" });
    expect(urls[0]).toContain("start_date=2026-08-08");
    expect(urls[0]).toContain("end_date=2026-08-22");
  });

  it("does not widen ranges carrying a time", async () => {
    const urls: string[] = [];
    fakeOura([[{}]], urls);
    await fetchAll("heartrate", {
      start: "2026-08-10T00:00:00Z", end: "2026-08-10T06:00:00Z" });
    expect(urls[0]).toContain("start_datetime=2026-08-10T00%3A00%3A00Z");
  });

  it("trims the extra days and says so", async () => {
    fakeOura([["2026-08-08", "2026-08-09", "2026-08-10", "2026-08-11", "2026-08-12"]
      .map((day) => ({ day }))]);
    const r = await fetchAll("daily_sleep", { start: "2026-08-09", end: "2026-08-11" });
    expect(r["n"]).toBe(3);
    expect(r["discarded_out_of_range"]).toBe(2);
  });

  it("a single day returns that day", async () => {
    // The case that was broken: [d..d] returned zero on daily_activity, sleep
    // and workout.
    fakeOura([[{ day: "2026-08-09" }, { day: "2026-08-10" }, { day: "2026-08-11" }]]);
    const r = await fetchAll("workout", { start: "2026-08-10", end: "2026-08-10" });
    expect(r["n"]).toBe(1);
  });

  it("reads the day from start_day when there is no day", async () => {
    fakeOura([[{ start_day: "2026-08-09" }, { start_day: "2026-08-30" }]]);
    expect((await fetchAll("enhanced_tag", {
      start: "2026-08-09", end: "2026-08-09" }))["n"]).toBe(1);
  });

  it("keeps what cannot be dated", async () => {
    // Discarding what you don't understand is the fastest way to under-deliver,
    // which is what this package exists not to do.
    fakeOura([[{ day: "2026-08-09" }, { sin_fecha: true }, { day: "2026-09-30" }]]);
    const r = await fetchAll("daily_sleep", { start: "2026-08-09", end: "2026-08-09" });
    expect(r["n"]).toBe(2);
  });

  it("catches the backwards range here, quoting the dates that were written", async () => {
    // With the margin, Oura would return a 400 quoting two dates the asker
    // never wrote.
    fakeOura([[{}]]);
    await expect(fetchAll("daily_sleep", { start: "2026-08-10", end: "2026-08-01" }))
      .rejects.toThrow(/2026-08-10.*2026-08-01/s);
  });

  it("dayOf reconoce las keys con hora", () => {
    expect(dayOf({ timestamp: "2026-08-09T12:00:00-06:00" })).toBe("2026-08-09");
    expect(dayOf({ bedtime_start: "2026-08-09T23:10:00-06:00" })).toBe("2026-08-09");
    expect(dayOf({ nada: 1 })).toBeNull();
    expect(dayOf("not an object")).toBeNull();
  });

  it("shiftDays returns its input untouched when it does not parse", () => {
    expect(shiftDays("2026-08-10", 2)).toBe("2026-08-12");
    expect(shiftDays("ayer", 2)).toBe("ayer");
  });
});

// ── What Oura silently ignores ────────────────────────────────────────────
describe("`latest` and `fields`", () => {
  it("rejects `latest` where Oura would ignore it", async () => {
    // Asking for the latest record and receiving ten while believing it is one
    // is worse than an error.
    fakeOura([[{}]]);
    await expect(fetchAll("daily_sleep", {
      start: "2026-08-01", end: "2026-08-10", latest: true })).rejects.toThrow(/is ignored/);
  });

  it("sends latest where it is honored, and requires no range", async () => {
    const urls: string[] = [];
    fakeOura([[{ bpm: 60 }]], urls);
    expect((await fetchAll("heartrate", { latest: true }))["n"]).toBe(1);
    expect(urls[0]).toContain("latest=true");
  });

  it("warns about fields that never appeared", () => {
    expect(ignoredFields(["score", "no_existe"], [{ day: "x", score: 1 }]))
      .toEqual(["no_existe"]);
    expect(ignoredFields(undefined, [{ day: "x" }])).toEqual([]);
  });
});

// ── Response shapes ───────────────────────────────────────────────────────
describe("response shapes", () => {
  it("reports a `data` that is not a list", async () => {
    // Wrapping the whole envelope would turn that into "one record" shaped like
    // `{data: …}` that looks legitimate.
    vi.stubGlobal("fetch", async () =>
      new Response(JSON.stringify({ data: { day: "2026-08-01" } }), { status: 200 }));
    await expect(fetchAll("daily_sleep", { start: "2026-08-01", end: "2026-08-01" }))
      .rejects.toThrow(/no interpretation is being invented/);
  });

  it("the unwrapped collections still work", async () => {
    vi.stubGlobal("fetch", async () =>
      new Response(JSON.stringify({ email: "x", age: 1 }), { status: 200 }));
    expect((await fetchAll("personal_info"))["n"]).toBe(1);
  });

  it("an empty response is zero records, not one", async () => {
    vi.stubGlobal("fetch", async () => new Response("{}", { status: 200 }));
    expect((await fetchAll("personal_info"))["n"]).toBe(0);
  });
});

// ── CSV ────────────────────────────────────────────────────────────────────
describe("CSV", () => {
  it("takes the header from the union, not from the first record", () => {
    // One record with an extra field is enough for that field to vanish without
    // a trace.
    const { columns, text, uneven } = toCsv([
      { day: "2026-08-10", score: 1 }, { day: "2026-08-11", score: 2, extra: 9 }]);
    expect(columns).toContain("extra");
    expect(text).toContain("9");
    expect(uneven).toBe(true);
  });

  it("puts the date first", () => {
    // It is the column a model joins against another source with.
    expect(toCsv([{ score: 1, day: "2026-08-10", aaa: 2 }]).columns[0]).toBe("day");
  });

  it("writes nested values as JSON in their cell", () => {
    // Flattening would invent columns Oura doesn't have; omitting would lose data.
    expect(toCsv([{ day: "x", contributors: { deep: 91 } }]).text).toContain('{""deep"":91}');
  });
});

// ── Size and emptiness ────────────────────────────────────────────────────
describe("warnings", () => {
  it("an enormous response comments on itself", () => {
    const heaviest = { day: "2026-08-01", met: Array.from({ length: 6000 }, (_, i) => i) };
    const warning = sizeWarning([heaviest, { ...heaviest }], undefined);
    expect(warning?.heaviest_field).toBe("met");
    expect(warning!.percentage).toBeGreaterThan(90);
  });

  it("does not nag if columns were already chosen", () => {
    const heaviest = { met: Array.from({ length: 6000 }, (_, i) => i) };
    expect(sizeWarning([heaviest, { ...heaviest }], ["met"])).toBeNull();
  });

  it("an empty query explains what is known", async () => {
    // `n: 0` does not distinguish between not wearing the ring, it not having
    // synced, asking for a future date, or lacking the permission.
    fakeOura([[]]);
    const r = await fetchAll("daily_sleep", { start: "2026-01-01", end: "2026-01-02" });
    const empty = r["empty"] as Record<string, string>;
    expect(empty["do_not_confuse"]).toContain("you didn't sleep");
  });

  it("says when the range is in the future", async () => {
    const manana = new Date(Date.now() + 30 * 86400_000).toISOString().slice(0, 10);
    fakeOura([[]]);
    const r = await fetchAll("daily_sleep", { start: manana, end: manana });
    expect((r["empty"] as { what_we_know: string[] }).what_we_know.join())
      .toContain("future");
  });
});

// ── The 429 and the errors ────────────────────────────────────────────────
describe("errors", () => {
  it("honors Retry-After and caps it", () => {
    expect(requestedWait("3", 0)).toBe(3000);
    expect(requestedWait("1800", 0)).toBe(8000);   // a generous header hangs nothing
    expect(requestedWait(null, 1)).toBe(2000);     // exponential backoff
  });

  it("translates pydantic's detail into something readable", () => {
    // Trimmed raw it left `{"detail":[{"type":"datetime_from_date_pars` and
    // nothing else.
    const m = detailOf(JSON.stringify({ detail: [{
      type: "datetime_from_date_parsing",
      loc: ["query", "start_date", "datetime"],
      msg: "Input should be a valid datetime or date",
      input: "ayer" }] }));
    expect(m).toContain("start_date");
    expect(m).toContain('"ayer"');
    expect(m).not.toContain("datetime_from_date_parsing");
  });

  it("reads the string form of detail too", () => {
    expect(detailOf(JSON.stringify({ detail: "Start time is greater" })))
      .toContain("Start time is greater");
  });

  it("un body ilegible no tumba nada", () => {
    expect(detailOf("<html>")).toBe("");
  });
});

// ── The token ─────────────────────────────────────────────────────────────
describe("Secret", () => {
  it("is not printed by accident", () => {
    const s = new Secret("abcdefghij");
    expect(String(s)).not.toContain("abcdefghij");
    expect(`${s}`).not.toContain("abcdefghij");
    expect(JSON.stringify({ s })).not.toContain("abcdefghij");
    expect(String(s)).toContain("10");            // the length yes, which is what diagnoses
    expect(s.reveal()).toBe("abcdefghij");       // revealing it is explicit
  });
});

// ── Sandbox ────────────────────────────────────────────────────────────────
describe("sandbox", () => {
  it("the profile explains instead of returning a bare 404", async () => {
    process.env.OURA_SANDBOX = "1";
    await expect(fetchAll("personal_info")).rejects.toThrow(/does not exist in Oura's sandbox/);
    await expect(fetchAll("personal_info")).rejects.toThrow(/Everything else works here/);
  });

  it("a made-up collection blows up before hitting the network", async () => {
    await expect(fetchAll("daily_vibraciones", { start: "2026-01-01", end: "2026-01-01" }))
      .rejects.toThrow(/is not an Oura collection/);
  });
});
