# oura-mcp

The [Oura](https://ouraring.com) v2 API as an [MCP](https://modelcontextprotocol.io)
server. All 19 collections, three tools, no dependencies beyond the MCP SDK.

**What sets it apart: Oura under-delivers without saying so, in four distinct
ways, and this server corrects all four.** That sounds minor and it is the whole
point — see below.

---

## The problem, measured

Oura does not return errors when it can't give you what you asked for. It
returns something different, shaped like a correct response. These are the four
we found by measuring against the real API on 9 August 2026:

### 1. Skip the pagination and you get a fraction

```json
{ "data": [ ... ], "next_token": "eyJ0eXAiOi..." }
```

If `next_token` comes back and you don't follow it, you receive the first page
and **nothing warns you**. One local day of `heartrate` — one person, one ring,
24 hours — is **1,231 samples across 2 pages**. A client that doesn't paginate
gets 1,000 of 1,231: 81%, looking complete. A month is ~37,000.

### 2. Asking for a single day returned zero records

`end_date` **does not behave the same across collections**:

| Exclude the last day requested | Include it |
|---|---|
| `daily_activity`, `sleep`, `workout` | `daily_sleep`, `daily_readiness`, `daily_stress`, `daily_spo2`, `daily_resilience`, `daily_cardiovascular_age`, `sleep_time` |

And on top of that, **`workout` filters by UTC date while reporting `day` in
local time**: at `-06:00`, asking for July 16–18 returned records from the 15th
and 16th — *before* the requested start.

Here the range is inclusive on both ends, always. Two extra days are requested
on each side and then trimmed, which is correct whichever way a given collection
behaves — and stays correct when Oura changes it.

### 3. `latest=true` is ignored where it doesn't apply

Only `heartrate` and `ring_battery_level` honor it. In the other seventeen Oura
doesn't error: it **returns the entire collection**. You ask for the latest
record, you get ten, and you believe it's one. Here it's rejected before the
request goes out.

### 4. A field that doesn't exist is silently ignored

`fields=does_not_exist` returns the **complete** record — the projection never
happens — and `fields=score,does_not_exist` applies the good one and drops the
bad one without a word. Here, fields that never appeared are reported under
`campos_ignorados`.

**The pattern is always the same:** you ask for one thing, you get another, and
nothing warns you. That's why this package would rather shout than quietly
under-deliver.

## Installation

### Try it with no credentials

```bash
pip install mcp-oura
OURA_SANDBOX=1 oura-mcp --revisar
```

The sandbox is official — it's in Oura's OpenAPI spec, with 34 mirror routes —
and serves synthetic data without authentication. 18 of the 19 collections work
there: `personal_info` doesn't, which makes sense, since it's the one returning
email, age, weight and height.

This is the right order: first you watch the server work and learn the shape of
the data, then you go get credentials.

### With your own data

**Oura stopped issuing Personal Access Tokens in December 2025.** Existing ones
still work; new ones can't be created. So there are two paths:

**a) OAuth2 — the one that works today.** Register an application at
[cloud.ouraring.com/oauth/applications](https://cloud.ouraring.com/oauth/applications)
with the redirect `http://localhost:9876/callback/` — **the trailing slash is
required**, the portal rejects the other form with `invalid_redirect_uri`.

```bash
export OURA_CLIENT_ID="…"
export OURA_CLIENT_SECRET="…"
oura-mcp --autorizar             # opens the browser, waits for the callback
oura-mcp --autorizar --manual    # headless machines: you paste the URL back
```

The token is stored in `~/.config/oura-mcp/credenciales.json` with mode 600 — or
in the system keychain if you happen to have `keyring` installed, which is not a
dependency of this package — and refreshes itself. `oura-mcp --olvidar` erases
it.

**b) A personal token, if you already had one.**

```bash
export OURA_PAT="your-token"
oura-mcp --revisar
```

`--revisar` is the self-check: it reports which credential you're using, which
scopes were granted and how long the access has left, **without returning the
token or a single health value**. It reports the token's length, never the
token. Error messages get copied and pasted into chats and issues; they have no
business carrying anything else.

### Connecting it to Claude Code

With the package installed (`pip install mcp-oura`):

```bash
claude mcp add -s user oura --env OURA_SANDBOX=1 -- oura-mcp
```

Drop `OURA_SANDBOX` once you've run `oura-mcp --autorizar`.

**If you use [uv](https://docs.astral.sh/uv/)**, nothing needs to be installed
permanently:

```bash
claude mcp add -s user oura --env OURA_SANDBOX=1 -- uvx --from mcp-oura oura-mcp
```

The `--from` is required because the distribution is named `mcp-oura` and the
executable `oura-mcp`. *(This needs `uv`; without it the command above fails
with "command not found", and `pip install` is the path to take.)*

As a Claude Code plugin:

```bash
claude plugin marketplace add proscar87/oura-mcp
claude plugin install oura@oura-mcp
```

### Connecting it to Claude Desktop

**One click:** download `oura-mcp.mcpb` from the
[releases page](https://github.com/proscar87/oura-mcp/releases) and double-click
it. Claude Desktop installs it — no terminal, no JSON, no Python. It ships with
sample data turned on, so it works before you have any credential at all.

When you want your own data, just ask it for something: it opens Oura's
authorization page through Claude, waits for the callback, and retries what you
asked. No terminal. That works because MCP has a mode for precisely this — URL
elicitation — and the client does the opening.

The one thing Oura still requires is that every application be registered, so you
need a client ID and secret from
[cloud.ouraring.com/oauth/applications](https://cloud.ouraring.com/oauth/applications)
once. That's Oura's rule, not this server's. `oura-mcp --authorize` remains for
terminal users and for clients that can't show a URL.

**Or by hand,** in `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "oura": {
      "command": "/full/path/to/oura-mcp",
      "env": { "OURA_SANDBOX": "1" }
    }
  }
}
```

`which oura-mcp` gives you the full path. Claude Desktop does not inherit your
terminal's `PATH`, so a bare name there fails silently — one of the most common
mistakes when configuring an MCP server.

## The tools

| | |
|---|---|
| `oura_collections` | All 19, what each one carries and which parameters it takes |
| `oura_query` | One collection in full over a range, paginating to the end |
| `oura_check` | Self-check that exposes nothing |

**Three, not nineteen.** A server with one tool per collection forces the model
to pick among 19 similar names before knowing what any of them contain. Here the
collection is a parameter and the catalog is consulted when needed.

All three declare themselves read-only, and that isn't a promise: there is no
`POST`, `PUT` or `DELETE` anywhere in the package, and a test reads the source to
keep it that way.

### `oura_query` parameters

| | |
|---|---|
| `dia` | A single day. Shorthand for `inicio=fin=dia` |
| `inicio`, `fin` | The range, **inclusive on both ends** |
| `campos` | Only these fields. Oura trims on its side, so less comes down |
| `ultimo` | The most recent record. `heartrate` and `ring_battery_level` only |
| `formato` | `json` or `csv`. Savings vary by collection: 55% on `heartrate`, 10% on `daily_sleep` |

And what the response tells you when something didn't come out clean:
`truncado` with `continuar_desde` to resume, `ciclo_de_paginacion` if Oura
repeats a token, `campos_ignorados`, `descartados_fuera_de_rango`,
`columnas_desiguales`, `vacio` when a query comes back empty, and
`respuesta_grande` when what's returned is heavy enough to matter.

That last one comes from measuring: **30 days of `daily_activity` is 252,000
characters**, and 87% of it is a single field, `met`, a per-minute MET series.
Asking for three columns with `campos` brings those same 30 days down to 5,000
characters — **99% less**. The server doesn't trim on its own — that would be
under-delivering — but it does say what's heavy and how to ask for less.

*(Parameter names are in Spanish because the codebase is. They're stable, they're
documented here, and the tool descriptions the model reads carry the same
information.)*

## What this server does NOT do

**It doesn't analyze.** No correlations, no anomaly detection, no period
comparison — which is exactly where other servers place their value.

The reason: an average computed in here reaches the model as a number without
its method. Across nine years of real data, **three out of four changes between
two consecutive measurements fall within the metric's own normal oscillation**. A
server that hands over "your HRV is up 12%" without saying how much that metric
swings on its own isn't informing you: it's manufacturing a signal.

Here you get the data. The analysis belongs where the method can be cited — for
instance with [cotejo](https://github.com/proscar87/cotejo), which draws exactly
that distinction for blood biomarkers.

## The 19 collections

**Daily summaries** — `daily_sleep`, `daily_readiness`, `daily_activity`,
`daily_stress`, `daily_spo2`, `daily_resilience`, `daily_cardiovascular_age`,
`vO2_max`

**The detail the scores hide** — `sleep` (stages, HRV, temperature, latency),
`sleep_time`, `workout`, `session`, `rest_mode_period`, `tag`, `enhanced_tag`

**High resolution** — `heartrate`, `ring_battery_level`

**No range** — `personal_info`, `ring_configuration`

Date-range collections use `YYYY-MM-DD`. `heartrate` and `ring_battery_level`
use ISO 8601 with time.

## Other Oura MCP servers

There are several as of August 2026, and it's worth being precise about the
differences. [`benngermin/oura-mcp`](https://github.com/benngermin/oura-mcp)
**paginates properly**, with a resumable cursor.
[`daveremy/oura-mcp`](https://github.com/daveremy/oura-mcp) shipped the
`end_date` fix the same week we did.
[`davidmosiah/oura-mcp`](https://github.com/davidmosiah/oura-mcp) has the most
complete MCP surface. Pagination no longer distinguishes anyone.

What does, as far as we could verify: **`workout`'s UTC skew isn't documented in
any of them**, nor is rejecting `latest` where Oura ignores it, nor warning about
fields that were never applied. And none of them treats not analyzing as a
stated position.

## Privacy Policy

This section exists because the Claude connectors directory requires one. It is
short because there is little to describe: the server runs on your machine and
talks to a single service, the Oura API.

**What is collected.** Nothing, by us. The health data you request goes from the
Oura API to your MCP client and passes through no server of ours, because there
isn't one.

**What is stored, and where.** Only your credentials, and only on your machine:

| | |
|---|---|
| OAuth2 tokens | `~/.config/oura-mcp/credenciales.json`, mode `600` — or the system keychain if you have `keyring` |
| Personal token | Wherever you put it: `OURA_PAT`, or the file `OURA_PAT_FILE` points to |

No health data is written to disk. There is no cache.

**Who it is shared with.** No one. The only outbound connection is to
`api.ouraring.com`, with your token, to fetch what you asked for. Oura's use of
your data is governed by [their privacy
policy](https://ouraring.com/privacy-policy), not by this one.

**How long it is retained.** Credentials, until you delete them:
`oura-mcp --olvidar`, or by removing the file. Health data isn't retained at all
— it lives in the response and that's it.

**Diagnostics expose nothing.** `oura_check` reports the token's length, never
the token; the profile's field names, never their values. The token is wrapped
in a type that won't print even in a stack trace.

**Contact.** [Repository issues](https://github.com/proscar87/oura-mcp/issues).

## A note on language

The code, its comments and the internal documents (`AGENTS.md`, `ROADMAP.md`,
`CHANGELOG.md`) are in Spanish, and so are the tool parameters. This README and
`llms.txt` are in English because they're what a stranger — or a directory
reviewer — reads first.

## License

MIT.

---

<!-- The MCP registry requires this line in the README of the package published
     to PyPI: it's how it verifies that whoever publishes the server also
     controls the package. Without it, `mcp-publisher publish` returns a 400. -->
mcp-name: io.github.proscar87/oura-mcp
