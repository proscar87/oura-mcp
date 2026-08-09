# For the next agent

State as of **9 August 2026**. Read this before touching anything.

## What this is

An MCP server over the Oura v2 API. **Its reason to exist is that Oura
under-delivers without saying so, and that's corrected here.**

Be careful how you tell that story, because it changed. An earlier version of
this file said the differentiator was pagination, and that "of the seven Oura
MCP servers, the most complete one doesn't paginate." **That is no longer
true**: `benngermin/oura-mcp` paginates properly, with a resumable cursor.
Pagination is table stakes now, not the edge. Don't repeat that line.

What does hold the project up are **four silent failures of the same family**,
measured against the real API and corrected here:

| | The failure | Where the fix lives |
|---|---|---|
| 1 | Not following `next_token` returns a fraction. One local day of `heartrate` is 1,231 samples across 2 pages | the pagination loop in the client |
| 2 | `end_date` is inconsistent **across collections**, and `workout` filters by UTC date while reporting `day` in local time | `MARGEN_DIAS` and the trim step |
| 3 | `latest=true` where it doesn't apply → Oura returns the **whole** collection | `CON_ULTIMO`, rejected before the network |
| 4 | `fields=made_up` → returns the complete record, no projection | the ignored-fields check |

If anyone proposes "simplifying" any of those four, the answer is no. They are
the product.

## Where it's published

| | |
|---|---|
| GitHub | https://github.com/proscar87/oura-mcp — public, MIT, CI green |
| PyPI | https://pypi.org/project/mcp-oura/ — 0.1.0, 0.1.1, **0.2.0** |
| MCP registry | `io.github.proscar87/oura-mcp` **v0.2.0**, active, latest |

The install name is `mcp-oura` because `oura-mcp` was already taken on PyPI by a
0.1.0 package with no author and no repository. The imported module is still
`oura_mcp`.

## How to publish a new version

```
# bump the number in pyproject.toml AND server.json — they must match
git tag v0.2.1 && git push origin v0.2.1
```

That runs the tests, publishes to PyPI and then to the registry. **There is no
secret configured and there must not be**: both publications go through OIDC,
with a single-use credential GitHub mints on the spot. PyPI's trusted publisher
is already registered as `proscar87` / `oura-mcp` / `publicar.yml` / environment
`pypi`.

Four things that cost time and shouldn't be repeated:

1. **The registry step must wait for PyPI.** It validates that the exact version
   exists there, and retries while the index propagates.
2. **The registry requires the line `mcp-name: io.github.proscar87/oura-mcp`** in
   the README of the *published* package. Deleting it returns a 400.
3. **`description` in `server.json` caps at 100 characters.** v0.2.0 shipped to
   PyPI and then failed the registry over six characters too many — and the retry
   loop blamed PyPI propagation five times in a row, hiding the real cause. Both
   are fixed; there's a test for the length now.
4. **Don't use `~/.pypirc`.** A malformed file made the parser dump a full token
   into a transcript.

## What's blocking, and it's yours

Two decisions an agent shouldn't make alone:

1. **The `.mcpb`.** Measured: the PyInstaller binary works with `--onedir`
   (0.41 s after the first run) but needs Apple notarization, CI on two
   platforms, and 45 MB per platform. TypeScript is cheaper *if the goal is
   Claude Desktop*. The Claude Code plugin already gives one-command install
   without any of it. **The question is scope, not technique.**
2. **What happens to the Python implementation** now that TypeScript exists.
   `mcp-oura` 0.2.0 is published and works; the port targets
   `@proscar87/oura-mcp`.

## What's already done

Eight correctness fixes and full OAuth2. **124 tests, none touch the network.**
The long version, with the measurements, is in `ROADMAP.md`. What you need to
know to avoid breaking it:

- **`OURA_SANDBOX=1`** points at Oura's mirror routes, which are official and
  accept any string as `Authorization`. Good for installing and watching the
  server work without credentials. **Useless for measuring API behavior**: it's a
  *generator*, not a filter — it returns n-1 records for any window, and zero for
  a one-hour window containing a sample. Measuring date semantics there gives
  wrong answers. That already happened once, in the first draft of the ROADMAP.
- **OAuth2** lives in the credentials module. Oura's refresh token is
  **single-use**: it is saved before being returned, atomically. Don't move that
  line. If two processes refresh at once — two MCP tools in parallel — the loser
  re-reads what's on disk instead of declaring the session lost.
- **The callback's `state` is verified** with a constant-time comparison. Without
  it, any page open in the user's browser can hand them an authorization code
  from another account.
- **The secret is wrapped in a type that won't print**, and getting the value
  requires an explicit call that greps cleanly.
- **The OAuth flow lives in the terminal**, never inside the MCP server. A server
  speaking over stdin/stdout can't open a browser or ask anyone anything.

## What's left

### Installation
- Done: Claude Code plugin (both manifests pass `claude plugin validate
  --strict`), `smithery.yaml`, `glama.json`, `llms.txt`, and `uvx` documented —
  with the caveat that **`uvx` requires `uv`**, so `pip install` is the
  no-prerequisites path.
- Left: the `.mcpb`, which depends on the decision above.

### Claude connectors directory
The viable door is the **desktop extension (MCPB)**: separate form, no Team
organization required. The tool annotations and the privacy policy it demands are
**already in place**. Missing: a 512×512 icon and the `.mcpb` itself.

The other door — remote connector — **requires a Team or Enterprise
organization** and hosting third-party health data. That's a decision, not a
to-do.

### Free and overdue
The three discovery files are in. Still missing: PRs to `awesome-mcp-servers`
and mcp.so, which is where most traffic comes from.

## Decisions NOT to revert

**Three tools, not nineteen.** One per collection forces the model to choose
among 19 similar names before knowing what any of them contain.

**It doesn't analyze.** No correlations, no anomalies, no period comparison —
which is where other servers place their value. An average computed inside
reaches the model as a number without its method, and across nine years of real
data three out of four changes between consecutive measurements are noise.
Handing over "your HRV is up 12%" without saying how much that metric swings on
its own isn't informing: it's manufacturing a signal. Analysis belongs where the
method can be cited — see [cotejo](https://github.com/proscar87/cotejo).

**Zero dependencies beyond the MCP SDK.** Not aesthetics: it's what makes
packaging as a binary viable. That's why `keyring` is imported inside a `try` and
never declared — it's installed here, but it comes from `twine`, not `mcp`, and a
user wouldn't have it.

**The secret does not live in the MCP client's config.** `OURA_PAT_FILE`, or the
0600 OAuth file. An MCP server is registered in a JSON that gets backed up,
synced, and shared when asking for help.

**`.garita.yml` stays.** [Garita](https://github.com/proscar87/garita) blocks
commits containing personal data or credentials, and runs in CI. The specific
risk here is someone pasting a **real** Oura response as an example into the
README or a test: `personal_info` returns email, age, weight and height. The
`exenciones` key must be **omitted**, not written as an empty list — `exenciones:
[]` trips Garita v0's parser, which reads it as the string `"[]"`.

## How it's tested

```
python -m pytest -q          # 124 tests, none touch the network
cd ts && npx vitest run      # the port's tests
```

**A CI that needs someone's token to pass isn't a CI: it's a dependency on that
person.** Don't add network tests to the mandatory CI.

What does go out to the network lives apart and never blocks a PR:

```
python herramientas/check_drift.py   # do the 19 still exist? (sandbox, no credentials)
python herramientas/smoke_stdio.py       # does the server actually start and speak stdio?
```

Both run weekly via `.github/workflows/deriva.yml`. The drift check catches a
renamed or retired collection; it does **not** catch a new one — the sandbox
can't be enumerated, and the script says so out loud. A check that pretends to
cover what it doesn't is worse than none.

The stdio smoke test exists because the 124 unit tests exercise functions, not
the process. The ugliest way an MCP server fails isn't returning wrong data: it's
failing the handshake, or writing something that isn't JSON-RPC to stdout. Both
look identical from the client — a server that "doesn't show up" — and no
function test catches either. It found the server announcing the wrong version on
its first run.

To test against the real Oura, with Oscar's token in `~/.oura_pat`:

```
OURA_PAT_FILE=~/.oura_pat python -m oura_mcp --revisar
```

**When measuring against the real API, print only counts and field names, never
values.** Not ceremony: transcripts get pasted elsewhere.

## Context you can't see in the code

This came out of auditing Oscar's health dashboard (`~/Developer/panel-salud`),
where the same failure mode — truncated data that looks complete — showed up
three times: PostgREST ignoring `limit` and cutting at 1,000 rows, and Withings'
`meastypes` returning 13 of 30 requested types with no error and no warning. That
last one was misdiagnosed for hours as an expired subscription.

Turns out Oura does the same thing in four different places. The thesis applied
in more spots than it claimed.

## A note on language

The repository is in English. It was written in Spanish through 0.2.0; the
translation and the tool-parameter rename land in 0.3.0, and the rename is a
breaking change recorded in the CHANGELOG.
