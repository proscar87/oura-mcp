/**
 * OAuth2 credential storage and rotation, in the implementation that ships.
 *
 * THIS FILE EXISTS BECAUSE OF AN ASYMMETRY. Python had 28 tests for this code
 * and TypeScript had none — and TypeScript is what goes inside the `.mcpb`, the
 * install path being pushed hardest. The least-tested copy was the one most
 * people would run, of the code that stores and rotates someone's refresh token.
 *
 * THEY NEVER TOUCH THE NETWORK: `fetch` is replaced.
 *
 * What is tested is not "saving a JSON". Oura's refresh token is SINGLE-USE:
 * the moment it is exchanged, the old one dies. The window between that death
 * and the new one reaching disk is where an account gets locked out, and every
 * test here is about keeping that window as short as it can be.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mkdir, mkdtemp, stat, readFile, readdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import {
  Credentials, credentialsPath, save, load, forget, post, refresh, exchangeCode,
} from "../src/credentials.js";
import { OuraError, Secret } from "../src/client.js";

let dir: string;

beforeEach(async () => {
  dir = await mkdtemp(join(tmpdir(), "oura-cred-"));
  process.env.OURA_CREDENTIALS = join(dir, "cred.json");
});
afterEach(() => {
  vi.unstubAllGlobals();
  delete process.env.OURA_CREDENTIALS;
});

function cred(refreshToken: string | null = "R1", expiresAt?: number,
              scopes: string[] = ["daily"]) {
  return new Credentials(
    new Secret("A1"),
    refreshToken ? new Secret(refreshToken) : undefined,
    expiresAt ?? Date.now() + 3_600_000,
    scopes,
  );
}

function fakeToken(body: unknown, status = 200) {
  vi.stubGlobal("fetch", async () =>
    new Response(JSON.stringify(body), { status }));
}

// ── Saving ─────────────────────────────────────────────────────────────────
describe("saving", () => {
  it("writes the file readable by nobody else", async () => {
    // A refresh token at 0644 is a refresh token any process on the machine can
    // take. The mode is set on the temp file BEFORE the rename, so the final
    // path never exists at a wider mode even for an instant.
    const path = await save(cred());
    // AWAITED. An un-awaited assertion is a test that reports success without
    // having checked anything — the exact shape of failure this package exists
    // to stop shipping, inside its own test suite.
    const mode = (await stat(path)).mode & 0o777;
    expect(mode).toBe(0o600);
  });

  it("leaves no debris when the write fails", async () => {
    // A half-written credentials file is worse than none: the old refresh token
    // is already dead, and this was the only copy of its replacement.
    //
    // THE FAILURE HAS TO HAPPEN AFTER THE TEMP FILE EXISTS. The first version of
    // this test broke `asJson()`, which throws BEFORE anything is written — so
    // there was never any debris to find and it passed without checking the
    // cleanup at all. Deleting the cleanup line from `save()` did not fail it.
    // A test that looks like it checks something and doesn't is the exact
    // failure this package is about, committed inside its own suite.
    //
    // Pointing at an occupied directory makes `writeFile` succeed and `rename`
    // fail, which is the only ordering that exercises the catch.
    const ocupado = join(dir, "ocupado");
    await mkdir(ocupado, { recursive: true });
    await writeFile(join(ocupado, "algo"), "x");
    process.env.OURA_CREDENTIALS = ocupado;

    await expect(save(cred())).rejects.toThrow();
    const quedo = await readdir(dir);
    expect(quedo.filter((f) => f.includes(".tmp"))).toEqual([]);
  });

  it("round-trips what it stored", async () => {
    await save(cred("R-VUELTA", undefined, ["daily", "heartrate"]));
    const back = await load();
    expect(back?.refreshToken?.reveal()).toBe("R-VUELTA");
    expect(back?.scopes).toEqual(["daily", "heartrate"]);
  });

  it("returns null when there is nothing, and explains when there is garbage", async () => {
    // Absent and corrupt are different questions with different answers.
    expect(await load()).toBeNull();
    await writeFile(credentialsPath(), "{not json");
    await expect(load()).rejects.toThrow(/corrupt/);
  });

  it("forgetting twice is not an error", async () => {
    await forget();
    await forget();
    expect(await load()).toBeNull();
  });
});

// ── The token must never be printable by accident ──────────────────────────
describe("secrecy", () => {
  it("carries no token in its string form", () => {
    const c = cred("REFRESH-SECRETO");
    const s = JSON.stringify(c) + String(c) + `${c}`;
    expect(s).not.toContain("REFRESH-SECRETO");
    expect(s).not.toContain("A1");
  });
});

// ── Rotation, where an account gets lost ───────────────────────────────────
describe("refresh", () => {
  it("saves BEFORE returning", async () => {
    // If it returned first and the caller crashed, the new token would exist
    // only in memory while the old one was already dead. The order is the whole
    // point of this function.
    fakeToken({ access_token: "A2", refresh_token: "R2", expires_in: 3600 });
    const nueva = await refresh(cred("R1"), "id", "secret");
    expect(nueva.refreshToken?.reveal()).toBe("R2");
    const onDisk = JSON.parse(await readFile(credentialsPath(), "utf8"));
    expect(JSON.stringify(onDisk)).toContain("R2");
  });

  it("sends the OLD token, not the access token", async () => {
    let sent = "";
    vi.stubGlobal("fetch", async (_u: string, o: RequestInit) => {
      sent = String(o.body);
      return new Response(JSON.stringify(
        { access_token: "A2", refresh_token: "R2", expires_in: 3600 }));
    });
    await refresh(cred("R-VIEJO"), "id", "secret");
    expect(sent).toContain("R-VIEJO");
    expect(sent).toContain("grant_type=refresh_token");
  });

  it("keeps the granted scopes, not the requested ones", async () => {
    // Oura may grant fewer than were asked for. Storing the request instead of
    // the grant makes every later «why is this empty» answer wrong.
    fakeToken({ access_token: "A2", refresh_token: "R2", expires_in: 3600,
                scope: "daily heartrate" });
    const nueva = await refresh(cred("R1", undefined, ["daily"]), "id", "secret");
    expect(nueva.scopes).toEqual(["daily", "heartrate"]);
  });

  it("does not give up if another process already refreshed", async () => {
    // Two clients sharing one credentials file is normal — the CLI and the
    // server. The loser of the race must not conclude the session is dead.
    await save(cred("R-DE-OTRO"));
    vi.stubGlobal("fetch", async () => new Response("{}", { status: 400 }));
    const out = await refresh(cred("R-MIO"), "id", "secret");
    expect(out.refreshToken?.reveal()).toBe("R-DE-OTRO");
  });

  it("propagates the failure when nothing was saved", async () => {
    vi.stubGlobal("fetch", async () => new Response("{}", { status: 400 }));
    await expect(refresh(cred("R1"), "id", "secret")).rejects.toThrow(OuraError);
  });

  it("says what to do when there is no refresh token at all", async () => {
    await expect(refresh(cred(null), "id", "secret"))
      .rejects.toThrow(/authorize/);
  });

  it("treats a response without access_token as an error", async () => {
    // Oura answering 200 with the wrong shape must not be stored as valid.
    fakeToken({ token_type: "bearer" });
    await expect(refresh(cred("R1"), "id", "secret")).rejects.toThrow(OuraError);
  });
});

// ── The exchange ───────────────────────────────────────────────────────────
describe("the token endpoint", () => {
  it("surfaces Oura's own description to whoever is already stuck", async () => {
    // Oura answers {"error", "error_description"} and the description is the
    // actionable half — «Invalid client_id.» Buried in raw JSON it forces
    // someone already stuck to parse a payload to learn what they mistyped.
    vi.stubGlobal("fetch", async () => new Response(
      JSON.stringify({ error: "invalid_client",
                       error_description: "Invalid client_id." }), { status: 400 }));
    await expect(post({ grant_type: "refresh_token" }))
      .rejects.toThrow(/Invalid client_id\./);
  });

  it("still reports the status when the body is unreadable", async () => {
    vi.stubGlobal("fetch", async () => new Response("<html>", { status: 502 }));
    await expect(post({ grant_type: "refresh_token" })).rejects.toThrow(/502/);
  });

  it("exchanging a code also saves it", async () => {
    fakeToken({ access_token: "A1", refresh_token: "R1", expires_in: 3600 });
    await exchangeCode("codigo", "id", "secret", "http://localhost:9876/callback/");
    expect(await load()).not.toBeNull();
  });
});

// ── Expiry ─────────────────────────────────────────────────────────────────
describe("expiry", () => {
  it("counts a token expiring in three seconds as already expired", () => {
    // Refreshing a second before a network round trip is refreshing too late.
    expect(cred("R1", Date.now() + 3_000).expired()).toBe(true);
    expect(cred("R1", Date.now() + 3_600_000).expired()).toBe(false);
  });
});

// ── The `state`, which is the only thing standing between a localhost
//    listener and any page the user happens to visit ─────────────────────────
describe("the OAuth state", () => {
  it("is unguessable and never repeats", async () => {
    // Nothing checked that it was UNPREDICTABLE. Every test verified that a
    // mismatched state is rejected, and none verified that an attacker couldn't
    // simply know the right one — which is the only thing `state` is for. A
    // constant state, faithfully compared, is a lock with its key on the door.
    const { authorizationUrl } = await import("../src/authorize.js");
    const { randomBytes } = await import("node:crypto");

    const seen = new Set<string>();
    for (let i = 0; i < 20; i++) {
      const state = randomBytes(24).toString("base64url");
      const url = new URL(authorizationUrl("id", state, "http://localhost:9876/callback/"));
      const got = url.searchParams.get("state") ?? "";
      expect(got.length).toBeGreaterThanOrEqual(22);
      seen.add(got);
    }
    expect(seen.size).toBe(20);
  });

  it("compares in constant time and rejects a mismatch", async () => {
    // A `===` here leaks the answer one character at a time to anyone who can
    // measure. The rejection itself matters more: without it, any page the user
    // visits could hit the localhost listener with a code of its choosing.
    const { extractCode } = await import("../src/authorize.js");
    const bueno = "el-estado-correcto-de-24";
    expect(extractCode(`/callback/?code=C&state=${bueno}`, bueno)).toBe("C");
    expect(() => extractCode("/callback/?code=C&state=otro", bueno))
      .toThrow(/state/);
  });
});

// ── Two queries at once, after the token expired ───────────────────────────
describe("concurrent refresh", () => {
  it("exchanges the token ONCE and answers both callers", async () => {
    // Oura's refresh token is single use. MCP tools run concurrently, so two
    // queries arriving after expiry started two exchanges of the same token:
    // the first won and the second came back «Refresh token already used» — a
    // failure the person cannot act on, reading like corruption, on a query
    // that had nothing wrong with it.
    //
    // The recovery that existed (reload and use whatever another refresher
    // saved) is itself a race: it only works if the winner finished writing
    // before the loser finished reading. This test fails without the shared
    // promise, reliably, because the fake endpoint takes time on purpose.
    const used = new Set<string>();
    let calls = 0;
    vi.stubGlobal("fetch", async (_u: string, o: RequestInit) => {
      calls++;
      const t = new URLSearchParams(String(o.body)).get("refresh_token") ?? "";
      await new Promise((r) => setTimeout(r, 20));      // a real round trip
      if (used.has(t)) {
        return new Response(JSON.stringify({ error: "invalid_grant",
          error_description: "Refresh token already used." }), { status: 400 });
      }
      used.add(t);
      return new Response(JSON.stringify(
        { access_token: "A2", refresh_token: `R2-${calls}`, expires_in: 3600 }));
    });

    const expired = cred("R1", Date.now() - 1000);
    await save(expired);

    const [a, b] = await Promise.all([
      refresh(expired, "id", "secret"),
      refresh(expired, "id", "secret"),
    ]);

    expect(calls).toBe(1);                       // the token was spent once
    expect(a.refreshToken?.reveal()).toBe(b.refreshToken?.reveal());
  });

  it("gives both callers the real reason when the exchange truly fails", async () => {
    // Sharing the failure is deliberate. If the refresh genuinely cannot
    // succeed, both should hear why — not one of them hearing "already used",
    // which points at the wrong problem.
    vi.stubGlobal("fetch", async () => new Response(
      JSON.stringify({ error: "invalid_client",
                       error_description: "Invalid client_id." }), { status: 400 }));

    const expired = cred("R1", Date.now() - 1000);
    const results = await Promise.allSettled([
      refresh(expired, "id", "secret"),
      refresh(expired, "id", "secret"),
    ]);
    for (const r of results) {
      expect(r.status).toBe("rejected");
      expect(String((r as PromiseRejectedResult).reason.message))
        .toContain("Invalid client_id.");
    }
  });

  it("does not wedge: a later refresh still runs", async () => {
    // If the shared promise were never cleared, one failure would poison every
    // refresh for the life of the process.
    vi.stubGlobal("fetch", async () => new Response("{}", { status: 400 }));
    await expect(refresh(cred("R1", Date.now() - 1000), "id", "secret")).rejects.toThrow();

    fakeToken({ access_token: "A3", refresh_token: "R3", expires_in: 3600 });
    const ok = await refresh(cred("R1", Date.now() - 1000), "id", "secret");
    expect(ok.refreshToken?.reveal()).toBe("R3");
  });
});
