/**
 * Client tests. THEY NEVER TOUCH THE NETWORK: `fetch` is replaced by a fake.
 *
 * What gets tested here are Oura's four silent failures and the three exits from
 * the pagination loop. A CI that needs someone's token to pass isn't a CI: it's
 * a dependency on that person.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { inspect } from "node:util";

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
    // These records carry no `day`, so there is nothing usable to continue from
    // and the message asks for a narrower range instead.
    expect(String(r["truncated"])).toContain("narrow the range");
    expect(r["continue_from"]).toBeUndefined();
  });

  it("names a day you can actually ask for when truncating", async () => {
    // `continue_from` was Oura's nextToken, and NO parameter accepts a token
    // back — deliberately, since a cursor parameter hands pagination to the
    // model, the failure this package exists to prevent. So the response told
    // the model to continue from a value it had nowhere to put.
    fakeOura(Array.from({ length: 20 }, (_, d) =>
      [{ day: `2026-01-${String(d + 1).padStart(2, "0")}`, score: 70 }]));
    const r = await fetchAll("daily_sleep",
      { start: "2026-01-01", end: "2026-12-31", pageLimit: 3 });
    expect(r["continue_from"]).toBe("2026-01-03");
    expect(String(r["truncated"])).toContain("start");
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
    // A SENTENCE, NOT A BARE NUMBER. This fires on essentially every dated
    // query, and `discarded_out_of_range: 2` reads as "2 of your records were
    // thrown away", the opposite of true.
    expect(String(r["discarded_out_of_range"])).toContain("2 record");
    expect(String(r["discarded_out_of_range"])).toContain("normal");
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

// ── Authorizing without a terminal ─────────────────────────────────────────
// A `.mcpb` installed with a double click must not end with "now open a
// terminal". MCP has a mode for exactly this — URL elicitation — and the flow
// runs from inside the conversation: the client opens Oura's page, the server
// listens for the callback it already knows how to listen for.
describe("authorization by elicitation", () => {
  it("asks the client to open Oura's page, not the user to open a terminal", async () => {
    const { authorizeByElicitation } = await import("../src/authorize.js");
    process.env.OURA_CLIENT_ID = "an-id";
    process.env.OURA_CLIENT_SECRET = "a-secret";
    const seen: Record<string, unknown>[] = [];
    await expect(authorizeByElicitation(
      async (p) => { seen.push(p); return { action: "decline" }; },
      undefined,
      "http://localhost:9873/callback/",
    )).rejects.toThrow(/was not completed/);
    expect(seen[0]!["mode"]).toBe("url");
    expect(String(seen[0]!["url"])).toContain("cloud.ouraring.com/oauth/authorize");
  });

  // NOTE: this test also guards an unhandled rejection. `cancel()` rejects a

  // promise nobody awaits (the caller throws its own error), and in Node that

  // kills the process — declining the prompt took the whole server down. No

  // assertion catches it; vitest reporting unhandled rejections as errors did.

  it("a declined prompt stops the listener instead of hanging", async () => {
    // Left running, a declined prompt keeps the tool call waiting the full five
    // minutes for a callback that will never come.
    const { authorizeByElicitation } = await import("../src/authorize.js");
    process.env.OURA_CLIENT_ID = "an-id";
    process.env.OURA_CLIENT_SECRET = "a-secret";
    const started = Date.now();
    await expect(authorizeByElicitation(
      async () => ({ action: "cancel" }),
      undefined,
      "http://localhost:9874/callback/",
    )).rejects.toThrow(/was not completed/);
    expect(Date.now() - started).toBeLessThan(3000);
  });

  it("without app credentials it says where to register them", async () => {
    const { authorizeByElicitation } = await import("../src/authorize.js");
    delete process.env.OURA_CLIENT_ID;
    delete process.env.OURA_CLIENT_SECRET;
    await expect(authorizeByElicitation(async () => ({}), undefined))
      .rejects.toThrow(/oauth\/applications/);
  });
});

// ── Sample data must never reach a model unlabeled ─────────────────────────
describe("the sandbox marker", () => {
  // This package's own thesis, turned on itself. `oura_check` said the sample
  // data was synthetic and the queries did not — so a fresh install, in the
  // DEFAULT configuration, answered "how did I sleep?" with a score out of
  // Oura's fake data and nothing marking it.
  //
  // The checkbox in the manifest defaults to on, and that's deliberate: off, a
  // stranger with no registered Oura application gets an error on their first
  // question instead of a working demonstration. On is only defensible because
  // of these tests.
  beforeEach(() => {
    process.env.OURA_SANDBOX = "1";
    delete process.env.OURA_PAT;
  });

  it("marks every collection, not just the one tried by hand", async () => {
    for (const c of ["daily_sleep", "sleep", "workout", "daily_activity"]) {
      fakeOura([[{ day: "2026-01-15", score: 73 }]]);
      const r = await fetchAll(c, { start: "2026-01-15", end: "2026-01-15" });
      expect(r["synthetic"], c).toBeDefined();
    }
  });

  it("marks it even when the answer is empty", async () => {
    // The reading most likely to be taken as "you have no data".
    fakeOura([[]]);
    const r = await fetchAll("daily_sleep", { start: "2026-01-15", end: "2026-01-15" });
    expect(r["synthetic"]).toBeDefined();
  });

  it("marks it in CSV too", async () => {
    // A wall of numbers with nowhere to put a caveat.
    fakeOura([[{ day: "2026-01-15", score: 73 }]]);
    const r = await fetchAll("daily_sleep",
      { start: "2026-01-15", end: "2026-01-15", format: "csv" });
    expect(r["synthetic"]).toBeDefined();
  });

  it("says whose it is not, and names the next step", async () => {
    // Wording, not just presence. "Sandbox mode" alone means nothing to a
    // person, and a warning with no next step leaves them stuck.
    fakeOura([[{ day: "2026-01-15" }]]);
    const r = await fetchAll("daily_sleep", { start: "2026-01-15", end: "2026-01-15" });
    const m = String(r["synthetic"]).toLowerCase();
    expect(m).toContain("not this person's");
    expect(m).toContain("connect");
  });

  it("is absent in real mode", async () => {
    // Otherwise it rides on every answer and stops being read.
    delete process.env.OURA_SANDBOX;
    process.env.OURA_PAT = "token-de-prueba";
    fakeOura([[{ day: "2026-01-15" }]]);
    const r = await fetchAll("daily_sleep", { start: "2026-01-15", end: "2026-01-15" });
    expect(r["synthetic"]).toBeUndefined();
  });
});

// ── A recovered 429 must not vanish ────────────────────────────────────────
describe("rate limiting", () => {
  it("says so when a retry succeeded", async () => {
    // A retry that SUCCEEDS left no trace: the caller waited, the answer came
    // back clean, and nothing said Oura had refused. The data is correct, so
    // this is not the same bug as the four this package was built for — but
    // being throttled is a fact about the NEXT query. A model that doesn't know
    // it was just refused asks for another fifty pages, and that one fails.
    let n = 0;
    vi.stubGlobal("fetch", async () => {
      if (n++ < 1) {
        return new Response("{}", { status: 429, headers: { "Retry-After": "0" } });
      }
      return new Response(JSON.stringify({ data: [{ day: "2026-01-01" }] }),
                          { status: 200 });
    });
    const r = await fetchAll("daily_sleep", { start: "2026-01-01", end: "2026-01-02" });

    expect(r["n"]).toBe(1);                       // the data still arrives
    const notice = String(r["rate_limited"]);
    expect(notice).toContain("429");
    expect(notice).toContain("complete");         // must not read as data lost
    expect(notice).toMatch(/smaller|wait/);       // and say what to do next
  });

  it("stays quiet when nothing was refused", async () => {
    // Otherwise it rides on every answer and stops being read.
    fakeOura([[{ day: "2026-01-01" }]]);
    const r = await fetchAll("daily_sleep", { start: "2026-01-01", end: "2026-01-02" });
    expect(r["rate_limited"]).toBeUndefined();
  });
});

// ── The most likely mistake on this tool ───────────────────────────────────
describe("fields as a string", () => {
  it("splits a comma-separated string and says it did", async () => {
    // Declared as string[], a model sending "day,score" got a raw validator
    // dump pointing at a library's documentation site. Technically correct, and
    // not an answer — exactly what this package exists to stop shipping.
    const urls: string[] = [];
    fakeOura([[{ day: "2026-01-01", score: 70 }]], urls);
    const r = await fetchAll("daily_sleep",
      { start: "2026-01-01", end: "2026-01-02", fields: "day, score" });

    expect(urls[0]).toContain("fields=day%2Cscore");
    expect(r["ignored_fields"]).toBeUndefined();  // splitting invents nothing
    expect(r["fields_split"]).toBeDefined();      // reinterpreting is announced
  });

  it("says nothing when the caller sent a proper list", async () => {
    fakeOura([[{ day: "2026-01-01", score: 70 }]]);
    const r = await fetchAll("daily_sleep",
      { start: "2026-01-01", end: "2026-01-02", fields: ["day", "score"] });
    expect(r["fields_split"]).toBeUndefined();
  });
});

// ── A bare date on a datetime collection ───────────────────────────────────
describe("whole-day widening", () => {
  it("turns a bare date into the whole day", async () => {
    // "What was my heart rate on January 1st" returned nothing: a bare date
    // went through untouched, start_datetime === end_datetime, an interval of
    // no duration. Oura returned zero and the empty-reason blamed Oura for a
    // window this client had emptied itself.
    const urls: string[] = [];
    fakeOura([[{ timestamp: "2026-01-01T10:00:00+00:00", bpm: 60 }]], urls);
    const r = await fetchAll("heartrate", { start: "2026-01-01", end: "2026-01-01" });

    expect(urls[0]).toContain("start_datetime=2026-01-01T00%3A00%3A00");
    expect(urls[0]).toContain("end_datetime=2026-01-01T23%3A59%3A59");
    expect(r["n"]).toBe(1);
  });

  it("leaves an explicit time exactly as given", async () => {
    // Widening only fills in what wasn't said.
    const urls: string[] = [];
    fakeOura([[]], urls);
    await fetchAll("heartrate",
      { start: "2026-01-01T08:00:00", end: "2026-01-01T10:00:00" });
    expect(urls[0]).toContain("start_datetime=2026-01-01T08%3A00%3A00");
    expect(urls[0]).toContain("end_datetime=2026-01-01T10%3A00%3A00");
  });

  it("does not touch the date collections", async () => {
    const urls: string[] = [];
    fakeOura([[]], urls);
    await fetchAll("daily_sleep", { start: "2026-01-05", end: "2026-01-06" });
    expect(urls[0]).toContain("start_date=2026-01-03");
    expect(urls[0]).not.toContain("T00");
  });
});

// ── What the mutation run exposed ──────────────────────────────────────────
describe("warnings actually reach the response", () => {
  it("puts ignored_fields in the response, not just in the helper", async () => {
    // `ignoredFields()` was tested as a function and NOTHING checked that its
    // result reached the caller. Deleting the line that attaches it to the
    // response broke no test at all — the helper worked, the wiring was
    // unguarded, and a warning that never arrives looks exactly like a query
    // with nothing to warn about.
    //
    // Found by breaking it on purpose. Python had the end-to-end test; this is
    // the same asymmetry that left credentials.ts untested.
    fakeOura([[{ day: "2026-01-01", score: 70 }]]);
    const r = await fetchAll("daily_sleep", {
      start: "2026-01-01", end: "2026-01-02", fields: ["score", "no_existe"] });
    expect(r["ignored_fields"]).toEqual(["no_existe"]);
  });

  it("describes a secret exactly the way Python does", () => {
    // It read `<secreto de N characters>` — Spanglish, and different from the
    // Python `<secret, N characters>`. This string surfaces in stack traces and
    // logs, which is where someone looks when a token is misbehaving, so the
    // two halves of one product must not describe it differently.
    expect(String(new Secret("abcdefghij"))).toBe("<secret, 10 characters>");
    expect(new Secret("abcdefghij").length).toBe(10);
  });

  it("stays hidden through every escape route a token has", () => {
    // THREE WAYS OUT, and only two were covered. `toString` and `toJSON` had
    // tests; `nodejs.util.inspect.custom` did not — and that is the one that
    // fires on `console.log(secret)` and inside stack traces, which is exactly
    // the scenario this class exists for. A token has already leaked here once,
    // through a traceback.
    const s = new Secret("TOKEN-QUE-NO-DEBE-SALIR");
    expect(String(s)).not.toContain("TOKEN-QUE-NO-DEBE-SALIR");
    expect(JSON.stringify({ s })).not.toContain("TOKEN-QUE-NO-DEBE-SALIR");
    expect(inspect(s)).not.toContain("TOKEN-QUE-NO-DEBE-SALIR");
    expect(inspect({ deep: { s } }, { depth: 5 }))
      .not.toContain("TOKEN-QUE-NO-DEBE-SALIR");
    // And it is still retrievable on purpose.
    expect(s.reveal()).toBe("TOKEN-QUE-NO-DEBE-SALIR");
  });
});

// ── CSV with values that shift columns ─────────────────────────────────────
describe("CSV and free text", () => {
  // `tag` and `enhanced_tag` carry `comment`: text the person typed. Commas,
  // quotes and newlines are not edge cases there, they are Tuesday. A CSV that
  // escapes them wrong doesn't fail — it shifts every column right, and the
  // numbers that come out are another field read under this one's name.
  //
  // Python gets this from the standard library. THIS ONE IS HAND-WRITTEN, which
  // is exactly why it needs the test the other one doesn't.

  /** A strict reader, deliberately not the code under test. */
  function parse(text: string): string[][] {
    const rows: string[][] = [];
    let row: string[] = [], field = "", quoted = false;
    for (let i = 0; i < text.length; i++) {
      const c = text[i];
      if (quoted) {
        if (c === '"' && text[i + 1] === '"') { field += '"'; i++; }
        else if (c === '"') quoted = false;
        else field += c;
      } else if (c === '"') quoted = true;
      else if (c === ",") { row.push(field); field = ""; }
      else if (c === "\n") { row.push(field); rows.push(row); row = []; field = ""; }
      else if (c === "\r") { /* bare CR outside quotes */ }
      else field += c;
    }
    if (field || row.length) { row.push(field); rows.push(row); }
    return rows;
  }

  it.each([
    ["a comma", "ran 5k, felt great"],
    ["quotes", 'they said "excellent"'],
    ["a newline", "line1\nline2"],
    ["CRLF", "a\r\nb"],
    ["a lone quote", '"'],
    ["a semicolon and tab", "a;b\tc"],
    // A LONE CARRIAGE RETURN, no newline after it. This one was a real bug:
    // Python quoted it and this implementation did not, because the regex
    // listed `\n` and not `\r`. Readers that end a row on a bare `\r` — Excel
    // among them — split the row there and shift every later column.
    ["a lone carriage return", "a\rb"],
  ])("survives %s and reads back identical", (_name, valor) => {
    const { text, columns } = toCsv([{ day: "2026-01-01", comment: valor, score: 73 }]);
    const rows = parse(text);

    expect(rows.length).toBe(2);                       // header + one row
    expect(rows[1].length).toBe(columns.length);       // nothing shifted
    const cell = Object.fromEntries(columns.map((c, i) => [c, rows[1][i]]));
    expect(cell["comment"]).toBe(valor);
    expect(cell["score"]).toBe("73");                  // a NUMBER stayed put
  });

  it("keeps nested structures in one cell", () => {
    const { text, columns } = toCsv([{ day: "2026-01-01", contributors: { deep: 90 } }]);
    const rows = parse(text);
    expect(rows[1].length).toBe(columns.length);
    expect(JSON.parse(rows[1][columns.indexOf("contributors")])).toEqual({ deep: 90 });
  });
});
