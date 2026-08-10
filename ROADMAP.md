# Roadmap

Written on **9 August 2026**, after reviewing the 431 Oura repositories on
GitHub and checking against the real API what is still alive and what isn't.

Three goals, in this order: **make it installable without knowing anything**,
**get it listed in Claude**, **cover what needs covering**.

The order of the *milestones*, however, is different — first you fix what
silently returns wrong data, because packaging a bug for one-click install only
distributes it faster.

---

## Already done

| | |
|---|---|
| GitHub | public, MIT, CI green |
| PyPI | `mcp-oura` 0.1.0, 0.1.1 and **0.2.0** |
| MCP registry | `io.github.proscar87/oura-mcp` v0.2.0, `active`, latest |

---

## The three findings that reordered the map

### 1. The date range was broken — **measured, and already fixed**

Asking for a single day returned **zero records** in three collections. No
error, no `truncated`, and `pages: 1` asserting the page came back complete.
That is exactly the failure mode this repository exists not to commit, on the
most common path of all: "how did I sleep last night?"

Measured against the real API on 2026-08-09, collection by collection, it is
**two distinct failures that stack**:

**a) `end_date` is inconsistent across collections.** Not "exclusive" flatly, as
`crcatala`'s note says — it depends which one:

| Exclusive (they lose the last day) | Inclusive |
|---|---|
| `daily_activity`, `sleep`, `workout` | `daily_sleep`, `daily_readiness`, `daily_stress`, `daily_spo2`, `daily_resilience`, `daily_cardiovascular_age`, `sleep_time` |

**b) `workout` filters by UTC date but reports `day` in local time.** At
`-06:00`, asking for `[16 Jul .. 18 Jul]` returned records from the **15th and
16th** — before the requested start. An evening workout lands on the next UTC
day.

*(A note on method: the sandbox is useless for measuring this. It's a
**generator**, not a filter: it returns `n-1` records for any window and 0 for a
one-hour window containing a sample. Measured there, everything looks exclusive.
The first version of this roadmap said exactly that, and it was wrong.)*

**The fix, already in the code:** request two extra days on each side and trim by
`day` on the client. Two, not one, because `workout` is exclusive *and* skewed,
and the two stack; the largest UTC offset in the world is ±14 h and the
exclusivity costs another day. A per-collection table wouldn't do — five
collections had no data to measure them with, and a table Oura changes fails
silently again. Widening and trimming is correct in all four cases and stays
correct when it changes.

Verified across the 13 collections that have data, at 1, 7 and 30 days: **all
correct**. The two discarded days are reported in `discarded_out_of_range`
rather than swallowed.

We didn't find it alone: `daveremy` shipped `fix(client): Oura treats end_date as
exclusive — single-day queries returned empty` the same week. The UTC skew isn't
documented anywhere.

### 2. Oura deprecated Personal Access Tokens in December 2025

New ones can't be created; existing ones still work. Verified from both sides:
the token in use **responds today**, and the creation page now redirects to the
new identity provider (`moi.ouraring.com`) — the migration `crcatala` documents.
Three projects updated that week had already moved to OAuth2.

> **This server installed foolproof for exactly one person.** Anyone else reached
> the README, read "it's a token and that's it", opened Oura's page, and found
> nowhere to create one.

That was the front door, bricked up for everyone except whoever already had a
key.

### 3. Oura publishes an OpenAPI spec, and it carries two parameters we weren't using

The `openapi.json` `spxrogers` maintains in their repo — "Oura API
Documentation", v2.0, 452 KB, with a drift check in CI — says every collection
accepts:

```
fields   Comma-separated list of fields to include in the response,
         in addition to the always returned fields.
latest   If True, returns most recent sample.   (heartrate, ring_battery_level)
```

That turns two features that had to be built into two parameters that have to be
passed. Three more confirmations come from the same spec:

- **Our table of 19 collections is complete.** 35 routes under
  `/v2/usercollection`; none missing.
- **The sandbox is official**: 34 mirror routes under `/v2/sandbox`.
- **Webhooks exist** (`/v2/webhook/subscription`), plus 32 `/{document_id}`
  routes.

---

## v0.2 — What's broken, and the sandbox · **COMPLETE**

None of this added tools. All of it corrects or cheapens. Eight points closed,
124 tests, none touching the network.

What wasn't in the plan and surfaced by measuring: `end_date` wasn't "exclusive"
but inconsistent per collection; `workout` is skewed to UTC; `latest` and
`fields` are silently ignored by Oura where they don't apply; and the sandbox is
a generator, not a filter, so it can't be used to measure API semantics. Four
failures of the same family — you ask for one thing, you get another, nothing
warns you — which is the same family as not paginating. The repository's thesis
applied in more places than it claimed.

### 1. Inclusive `end_date`, and a test per collection — **done**

Two extra days on each side, and a trim by `day` on the client. Two and not one
because the two failures stack: exclusivity costs a day and the UTC skew another.
Correct whether the endpoint is inclusive or exclusive, and whether the skew runs
forward or backward — which is what keeps it correct when Oura changes it.

Verified collection by collection against the **real** API, not the sandbox:
fixing it in `daily_sleep` didn't fix it in `workout`, and the sandbox lies about
this.

Plus a convenience parameter borrowed from `spxrogers`: **`day`**, for a single
date. The trap stops existing if the common path — "how did I sleep last night?"
— doesn't force you to write a range.

### 2. Sandbox mode — **done**

Verified: `https://api.ouraring.com/v2/sandbox/usercollection/…` **accepts any
string as `Authorization`** and returns synthetic data.

An `OURA_SANDBOX=1` that changes the base and nothing else. It's worth three
things at once:

- **Foolproof installation**: install it, try it, watch it work, and *then* fight
  with authentication. The order used to be backwards, and that's where people
  were lost.
- **The Claude directory asks for it**: review requires test-account instructions
  "detailed enough for a reviewer to access your server end to end". A sandbox
  mode is that answer in one line.
- **CI against the real API** without depending on anyone's token.

What the sandbox does **not** give: `heartrate` returns 2 samples and no
`next_token`. Good for demonstrating, not for testing pagination. That's still
tested with the fake API in `tests/`.

### 3. `fields` and `latest`, passed through to Oura — **done**

- `fields: ["bpm"]` → **trims on Oura's side**: saves bandwidth as well as
  context.
- `latest: true` → answers "my most recent heart rate", which previously could
  only be answered by pulling the entire window.

**And both turned out to carry their own silent failure**, measured 2026-08-09:

| What you ask for | What Oura does |
|---|---|
| `fields=made_up` | Returns the **complete** record. The projection never happens |
| `fields=score,made_up` | Applies the good one, drops the bad one, says nothing |
| `latest=true` on `daily_sleep` | **Ignores it and returns the entire collection** |

Neither errors. Same family as not paginating: you ask for one thing, you get
another, nothing warns you. So `latest` is **rejected here** for the 17
collections that don't honor it — before going near the network — and fields that
appeared in no response are reported in `ignored_fields`.

One finding that helped: **`fields` always returns `day` and `id`**, so the date
trim in point 1 doesn't break when someone projects columns.

Also, one thing the API doesn't provide and is now built: **`format: "csv"`**,
the same table without repeating the keys 37,000 times. Savings vary by
collection: 55% on `heartrate`, 10% on `daily_sleep`. The header comes from the
union of all keys, not the first record — taking it from the first loses an
entire field silently — and if records don't share keys the response says so,
because an empty cell can mean "absent field" or "null value".

*(The same measurement produced the number the README was missing: one local day
of `heartrate` is **1,231 samples across 2 pages**. A client that doesn't
paginate receives 1,000 of 1,231 — 81% — with no warning at all.)*

### 4. A 429 wasn't retried — **done**

It gave up on the first one. On a query that chains up to 50 requests, that
throws away everything already fetched. It now retries twice, honoring
`Retry-After` in both its forms (seconds and HTTP date), with exponential backoff
when it's absent and an 8 s cap so a generous header can't hang the conversation.
**Only the 429**: a 401 doesn't improve by waiting.

And a measurement worth writing down: **Oura sends no rate-limit headers** on
successful responses — no `X-RateLimit-Remaining` or equivalent. A client can't
know how close it is to the ceiling; it only finds out once it's been refused.
Reacting well is all that's left.

### 5. `truncated` warned but didn't let you continue — **done**

It said "shorten the range". Correct, but the model could do nothing but retry
blind. `benngermin` returns `{records, truncated, nextToken}` so the caller can
resume. Now the cursor comes back too: `truncated` plus `continue_from`, and
`fetch` accepts it. **This isn't analysis** — it's transport, and the natural
extension of the loop that is the product.

### 6. Tool annotations — **done**

All three declare `title`, `readOnlyHint`, `destructiveHint` and
`idempotentHint`. And `openWorldHint` true, which almost nobody sets: the data
comes from an external service and the same call twice can differ if the ring
synced in between. Saying otherwise would invite memoization.

There's also a test that **reads the source** looking for `POST`, `PUT`, `DELETE`
and `PATCH`. The read-only annotation is true today; that test is what finds out
the day it stops being.

### 7. The token, out of every `repr` — **done**

The credential is no longer a plain string: it's a type whose printed form says
`<secret, 32 characters>`. Getting the value requires an explicit call — visible
in the code and greppable.

Not theoretical paranoia: a malformed `~/.pypirc` already made a parser dump a
full token into a transcript. The lesson wasn't "be more careful", it was that
care doesn't hold up by hand.

### 8. Collection drift, in CI — **done, but not as written**

The plan said "compare `collections.py` against Oura's `openapi.json`". **You
can't: Oura doesn't publish its spec at any stable URL.** Five plausible paths,
five 404s. The only public copy is vendored in `spxrogers`' repository, and
hanging our CI off a third party's repo trades one dependency for a worse one.

What is possible, and already runs: `tools/check_drift.py` asks after the 19
collections **against the sandbox**, which needs no credentials. Weekly and on
demand, never on push — a test that goes out to the internet can't decide whether
a PR lands.

With its limits said out loud, which is half the value:

| Catches | Doesn't catch |
|---|---|
| A renamed, moved or retired collection | A **new** collection |

The sandbox can't be enumerated, so discovering additions is still human work.
Saying that in the script itself is worth more than a check that appears to cover
something it doesn't.

---

## v0.3 — OAuth2, the front door · **COMPLETE**

Without this the server is useless to anyone new. Personal tokens stay supported
and quiet: whoever already has one shouldn't have to migrate, and `OURA_PAT` /
`OURA_PAT_FILE` still win when set.

Endpoints: authorization at `cloud.ouraring.com/oauth/authorize`, token at
`api.ouraring.com/oauth/token`, revocation at `/oauth/revoke`. Eight scopes:
`email`, `personal`, `daily`, `heartrate`, `workout`, `tag`, `session`, `spo2`.

Three things others learned the hard way:

- **The refresh token is single-use.** It has to be rotated and **persisted
  before** being consumed, or a race leaves the session dead (`crcatala`).
- **The redirect URI needs the trailing slash.** The portal rejects `…/callback`
  with `invalid_redirect_uri` and accepts `…/callback/`.
- **`--manual` for machines with no browser**: print the URL, the user opens it
  wherever, and pastes the failed callback URL back.

And a fourth, from `davidmosiah`: the scopes the consent screen returns aren't the
ones you asked for — the user can grant fewer. The **granted** ones are stored,
not the requested ones, and `oura_check` reports both lists. That's the answer to
the question people ask most when something comes back empty: "is there no data,
or did I not grant permission?"

**What shipped, and one decision that wasn't in the plan.** The flow lives in
`oura-mcp --authorize`, in the terminal, **never inside the MCP server**: one
that speaks over stdin/stdout can't open a browser or ask anyone anything, and
pretending otherwise is how you hang an MCP client forever. With `--manual` for
headless machines, and `--forget` to revoke locally.

**The `state` is verified, and it wasn't optional.** The callback arrives at an
HTTP server on localhost that serves whatever it's sent. Without comparing the
`state`, any page open in the user's browser can hand them an authorization code
from **another account** and leave them connected to data that isn't theirs, with
nothing looking wrong. It's generated with a CSPRNG and compared in constant time.

**And the "missing token" message changed**, which was what supported finding #2
of this roadmap. It used to point at the personal-tokens page — which since
December 2025 issues none — and whoever landed there got stuck without knowing
why. It now offers three paths, from least to most paperwork, and the first
requires signing up for nothing:

```
  1. OURA_SANDBOX=1 — sample data, no signup of any kind
  2. oura-mcp --authorize — OAuth2, once, in the browser
  3. OURA_PAT / OURA_PAT_FILE — only if you already had one
```

**Where the tokens live — with a correction.** The plan said "system keychain
falling back to a `0600` file". On going to do it: `keyring` **is not a
dependency of this package and mustn't be**. It's installed here, but it comes
from `twine`, not `mcp`; a user wouldn't have it. And an empty dependency list is
exactly what makes packaging this as a binary viable.

What shipped: **a `0600` file, written atomically, in a `0700` directory** — and
the keychain **only if it happens to be installed**. Whoever has it wins; whoever
doesn't loses nothing.

**The rotation is the dangerous part, and it's done.** Oura's refresh token is
single-use: the moment the request goes out, the one we held is dead. Between the
response and the save there's a window where the old one has died and the new one
doesn't exist on disk; crashing there loses the session. The refresh saves
**before returning**, atomically — you can't do better, because Oura offers no
two-phase exchange, but you can make the window as short as possible and ensure a
half-written file never exists.

And one that wasn't foreseen: **two processes refreshing at once** is a real case
— two MCP tools called in parallel — and the one that loses the race gets a 400
even though the session is alive. Before declaring it lost, it re-reads what's on
disk.

---

## v0.4 — Installing without a terminal

The ladder, from cheapest rung to most expensive.

### 1. `uvx` documented — **done, with a correction**

Every competitor is TypeScript and installs with `npx -y`. The Python equivalent
is `uvx --from mcp-oura oura-mcp`, and it's in the README.

**But not as the default path, and that was the first draft's mistake.** `uvx`
requires having `uv` installed. It isn't installed on this machine, which is how
it was discovered: a README that opens with "nothing to install" and gives a
command that answers `command not found` is exactly the opposite of the goal.
`pip install mcp-oura` is the no-prerequisites path; `uvx` is the upgrade for
whoever already has `uv`.

Along the way, another one that was missing: **Claude Desktop doesn't inherit the
terminal's `PATH`**, so its JSON needs the full path from `which oura-mcp`. A
bare name there fails silently, and it's one of the most common mistakes when
configuring an MCP server.

### 2. Claude Code plugin — **done and validated**

`.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json`, both passing
`claude plugin validate --strict` against the CLI's real validator, not against a
schema someone assumed.

```bash
claude plugin marketplace add proscar87/oura-mcp
claude plugin install oura@oura-mcp
```

No `env` block, deliberately: I didn't verify that this schema interpolates
variables, and a plugin silently falling back to the sandbox would show synthetic
data as if it were yours. The server's own "no credentials" message already
offers the three paths.

### 3. MCPB — the one-click `.mcpb`

An `.mcpb` is a zip with the server and a `manifest.json`; it installs with a
double click in Claude Desktop, no terminal and no JSON. `user_config` with
`"sensitive": true` generates the field's UI on its own and stores the value in
the secure store. It is, literally, the definition of foolproof.

**The problem is Python.** Anthropic's documentation is explicit: Node.js "ships
with Claude Desktop on macOS and Windows, so users need no separate runtime".
Python doesn't.

**It was measured rather than assumed.** Binary built with PyInstaller on
2026-08-09, macOS arm64:

| Variant | Size | First start | Subsequent |
|---|---|---|---|
| `--onefile` | 22 MB | 7.6 s | **6.5–7.6 s, every single run** |
| `--onedir` | 45 MB | 7.8 s | **0.41 s** |
| `python -m oura_mcp` | — | 0.40 s | 0.40 s |

Two things change the decision:

1. **`--onefile` is disqualified.** It unpacks 22 MB into a temp directory every
   time it starts. An MCP server that takes seven seconds to answer the handshake
   looks hung, in every session.
2. **`--onedir` does work** — 0.41 s after the first run, same as Python. The
   initial 7.8 s is Gatekeeper verifying a binary that is **ad-hoc signed only**
   (`flags=0x2(adhoc)`, verified with `codesign`).

And there's the cost the table doesn't show: distributing that seriously requires
**an Apple Developer ID and notarization**, plus macOS and Windows runners in CI,
and ~45 MB per platform. All so Claude Desktop can start a Python interpreter
that only runs our 1,281 lines.

| | What it implies | Verdict |
|---|---|---|
| `type: "python"` | Depends on the user's Python | Doesn't meet the goal |
| `type: "binary"` (`--onedir`) | 45 MB × 3 platforms, Apple notarization, CI on macOS and Windows | Viable, but the price is high |
| Port to TypeScript | Rewrite 1,281 lines of source and 936 of tests | Node is already bundled: no binary, no signing, no per-platform CI |

**The measurement inverted the recommendation.** It used to say "binary, because
it preserves the work already done". With the numbers in hand, the binary costs
notarization plus three builds plus 135 MB of artifacts — all for the milestone
whose entire point is that installing be trivial. If the `.mcpb` is genuinely
wanted: **TypeScript**.

**The port exists and has verified parity.** Five queries in both
implementations return the same `n` and the same page counts, and in the case
that justifies the project — one local day of `heartrate`, 1,231 samples across 2
pages — both return exactly the same records in the same order.

A lesson about differential testing came out of it: the first comparison used
SHA fingerprints and reported a difference. The data didn't differ — Python's
`json.dumps` puts a space after every comma and `JSON.stringify` doesn't, so
identical content hashed differently. A test that compares serializations
compares serializers.

---

## v0.5 — Listed in Claude

There are two doors and they are not interchangeable.

### Door A — Desktop extension (MCPB) · **the viable one**

A separate form, at `clau.de/desktop-extention-submission`. **No Team or
Enterprise organization required.**

- [ ] A working `.mcpb` (v0.4)
- [x] Annotations on all three tools (v0.2)
- [x] **Privacy policy** — a "Privacy Policy" section in the README, already
      written: collection, use, storage, third parties, retention and contact.
      Still missing the `privacy_policies` array in `manifest.json`, which only
      exists once the `.mcpb` is built.
      *"Missing or incomplete privacy policies result in immediate rejection."*
- [ ] 512×512 PNG icon
- [ ] Installation and usage documentation
- [ ] Examples exercising each tool (the sandbox gives these for free)

### Door B — Remote connector · **closed for now**

The submission portal lives in Claude.ai's admin settings and **requires a Team
or Enterprise organization**; it doesn't appear on individual plans. It also
requires a hosted HTTPS server (streamable HTTP or SSE), OAuth 2.0, and declaring
that it handles personal health data — which it does.

That's the route to Claude on web and mobile, and hosting third-party health data
is a serious commitment, not a weekend. It goes here as a conscious option, not a
to-do.

---

## The competition, as of 9 August 2026

431 repositories searching for "oura ring". Most of it is noise — two SEO
`.github` repos, a tamagotchi, Adobe test repos — but underneath the noise
something happened that has to be said plainly.

### One by one, and what to take from each

**[spxrogers/oura-toolkit](https://github.com/spxrogers/oura-toolkit)** · Rust ·
the best-engineered of the lot, and the closest in judgment.

CLI + five generated SDKs + MCP + plugin, all from an `openapi.json` with
`spec-drift.yml` in CI. Publishes to crates.io **and** npm **via OIDC with
Trusted Publishing and provenance** — the same "no secret to rotate" stance,
applied to two more registries. Their commits read like a shopping list:

- `Rate-limit handling: honor 429 + Retry-After, one bounded retry, typed error`
- `Headless auth: --no-browser login, OURA_ACCESS_TOKEN, OURA_API_BASE_URL`
- `MCP + CLI: single-day date convenience parameter`
- `Auth: redact TokenResponse Debug`

**Take:** all four. They're distributed across v0.2 and v0.3.

---

**[davidmosiah/oura-mcp](https://github.com/davidmosiah/oura-mcp)** · TS ·
0.4.11 · the most complete MCP surface of the lot.

Resources (`oura://capabilities`, `oura://latest/readiness`), prompts,
`OURA_CACHE=sqlite`, three privacy modes, `oura_demo` with synthetic data tagged
`is_demo: true`, `smithery.yaml`, `glama.json`, `llms.txt`. Part of a **registry
of nine health connectors** with a single installer.

Their fixes are a useful confession: `stop all_pages truncating data` (they had
our bug), `latest/readiness is the newest record by construction`, `doctor
accepts full Oura consent scopes`. And they document the trap nobody else spotted:
**Oura serves oldest-first and accepts no sort parameter**, so `limit: 1` returns
the **oldest** record.

**Take:** the three discovery files, the resources, the demo mode. **Don't take:**
the `"recommendation": "green light for moderate-to-high intensity"` — a template
over a score, presented as advice. That's the number without its method.

---

**[benngermin/oura-mcp](https://github.com/benngermin/oura-mcp)** · TS · 12 tools
· stdio + multi-tenant HTTP.

The only one that genuinely competes on what we thought was ours: **it paginates
properly and returns a resumable cursor** (`{records, truncated, nextToken}` with
`maxRecords`). It advertises itself as "first-party" but it belongs to its
author's own LifeOS, not to Oura — 3 commits, 0 stars.

**Take:** the resumable cursor.

---

**[crcatala/oura-cli](https://github.com/crcatala/oura-cli)** · TS · a CLI, not
an MCP server · the best documentation of the API's quirks.

OS keychain with a 0600 fallback, `--sandbox`, `oura doctor`, automatic JSON when
piped, disciplined exit codes (0/1/2/130), opt-in read-only live tests triggered
by a `/run-live-tests` comment. Its "Notes & quirks" section is three paragraphs
worth weeks.

**Take:** the three quirks, and the pattern of live tests that never block a PR.

---

**[daveremy/oura-mcp](https://github.com/daveremy/oura-mcp)** · TS · 4★ · the
most-installed of the MCP servers.

`claude plugin marketplace add`, `npx -y`, and an `/oura` skill that "orchestrates
the MCP tools into conversational responses instead of raw JSON" — which is
exactly the separation this roadmap proposes. Their commit from that week is our
confirmed bug.

**Take:** the plugin structure, and the skill as an interpretation layer separate
from the server.

---

**[echocharlie/oura-mcp-server](https://github.com/echocharlie/oura-mcp-server)**
· Python · FastMCP · read-only.

Eight tools, **all returning compact CSV with the units in the column names**,
and designed to *compose with a Strava connector*: everything keyed by ISO date
so the model can join training load against recovery in a single reasoning step.
Still uses a PAT — more confirmation that old tokens still work.

**Take:** CSV with units, and above all **composition by date**.

---

**The rest, one line each:**

| | |
|---|---|
| [Th0rgal/open_oura](https://github.com/Th0rgal/open_oura) · Rust · **475★** | Reverse-engineered BLE: never touches the cloud. The ecosystem's center of gravity. **No license** — nothing can be reused |
| [louispires/…Home-Assistant](https://github.com/louispires/Oura-Home-Assistant-Integration) · 58★ | OAuth2. The migration is general, not an MCP fad |
| [entorb/analyze-oura](https://github.com/entorb/analyze-oura) · 10★ · since 2022 | The oldest and still alive. Streamlit + pandas: analysis, and honest about being that |
| [kesslerio/oura-analytics-openclaw-skill](https://github.com/kesslerio/oura-analytics-openclaw-skill) · 6★ | The "skill" form factor, not a server. There's demand for that layer |
| [legnoh/oura-exporter](https://github.com/legnoh/oura-exporter) · 6★ · since 2023 | Prometheus. Another consumer of the same raw data |
| [narwhaldc/TA-oura](https://github.com/narwhaldc/TA-oura) | Normalizes Oura into a canonical wearables model. The common-schema idea, in Splunk form |
| [Schimmilab/oura-mcp-server](https://github.com/Schimmilab/oura-mcp-server) | "intelligent analysis and recovery insights". 0★ since Dec 2025 |
| `oura-ring/.github`, `oura-portable-charger/.github` | Pure SEO. Noise |

### What this means

**Pagination is no longer a differentiator.** AGENTS.md used to say "of the seven
Oura MCP servers, the most complete one doesn't paginate". That was true and is
no longer: `benngermin` paginates with a resumable cursor, a rung above what we
did until that night. That line had to be corrected before someone verified it.

What does remain ours, and is worth defending:

- **Three tools, not twelve or nineteen.** Everyone else sits at 8–12.
- **It doesn't analyze, deliberately, and argues why.** It's the only editorial
  position in the set.
- **Zero dependencies** beyond the MCP SDK.
- **It shouts when it under-delivers.** Nobody else has a `truncated` with that
  intent — and after v0.2, with a cursor to continue from.

The natural home for analysis is a **Claude Code skill** — like `daveremy`'s —
that carries the method and cites it, while the server keeps handing over the
data. That way "more features" and "doesn't analyze" stop conflicting: they
separate into two artifacts, each honest about what it does.

---

## What the WHOOP ecosystem answers for us

Checked on 10 August 2026. WHOOP's MCP landscape is far more crowded than
Oura's — at least ten servers — and being second means the questions we're still
arguing about have already been answered out loud by someone else.

### The one that mattered: nobody ships credentials

The open question was whether to embed OAuth app credentials so a user never has
to register an application. **Every WHOOP server examined requires the user to
register their own app.** `nissand/whoop-mcp-server-claude` (18 tools, full
OAuth) and `jonnyhaynes/whoop-mcp-server` (10 tools) both say so plainly in
their setup steps.

So the one-time client ID and secret isn't our defect — it's what this category
looks like when the vendor requires registered applications. It stops being an
open decision. What's left is making that single step short and impossible to
get wrong, which the manifest already does by spelling out the trailing slash
that otherwise bounces the registration.

### The anti-pattern, confirmed in the wild

`jonnyhaynes/whoop-mcp-server` exposes `nextToken` **as a tool parameter**. That
hands pagination to the model: it has to notice the token came back, decide to
call again, and keep going until it stops. A model that forgets gets a partial
answer that looks complete — the exact failure this package exists to prevent,
shipped as an interface.

We paginate to exhaustion inside the server and report `pages`. Same API
constraint, opposite place to put the burden. This is the clearest outside
confirmation of the thesis so far, because it isn't an argument — it's a
competitor's parameter list.

### 47 tools, and still no analysis

`thebriangao/totem` is the most ambitious in the category: 47 tools, read *and*
write, against WHOOP's private iOS API. Worth reading for two reasons.

It performs **no server-side analysis** — no trends, no averages, no
correlations — despite having every opportunity. It reshapes nested responses
into flat objects and stops there. Arrived at independently, that's the same
line we drew, and it holds even at fifteen times our tool count. The principle
isn't a consequence of being small.

And it's honest about what it costs: *"this works through WHOOP's private iOS
API rather than the public OAuth API. That isn't what WHOOP's terms allow."* It
warns that WHOOP may suspend API access or terminate the membership. That's the
trade we are not making — Oura's public API gives us everything we ship, and a
server that can get someone's account closed isn't foolproof to install no
matter how good the install is.

### What the stars actually reward

The highest-starred WHOOP repository isn't an MCP server at all. `OpenStrap/edge`
(427 stars) pairs a WHOOP 4.0 over Bluetooth and makes it useful **without a
subscription**. `satayutata/geniemax-core` (126 stars) is a health-analytics
engine whose description ends "no subscription."

Oura doesn't paywall its API, so there's no subscription to escape and no
equivalent lever here. Worth knowing what the attention in this category is
really for, and not mistaking it for interest in MCP servers.

## What is NOT on the roadmap

Held over from AGENTS.md, and with more reason now that every competitor does the
opposite:

- Analysis tools, correlations, anomaly detection, period comparison.
- One tool per collection.
- **Webhooks.** They exist in the spec, but they require a public endpoint and
  break the local model. A server running on your machine can't receive a POST
  from Oura without ceasing to be local.
- A PyPI token in `secrets` — both publications go through OIDC.
- Tests that go out to the internet in the mandatory CI. The sandbox and the
  drift check are *optional* work, never a requirement for a PR to pass.

### Conditionally: caching

Oura's historical data doesn't change; re-requesting the same month of
`heartrate` throws 37,000 records of network away. `davidmosiah` uses
`OURA_CACHE=sqlite`, optional. It only lands here if it betrays neither of two
things: zero dependencies (sqlite is standard library, so that's fine) and **that
it never serves stale data silently**. A cache that quietly answers with
yesterday's is the same sin as not paginating. If it's built, the response
carries `from_cache` and the date it was fetched.

---

## A strategic note, outside the code

`davidmosiah` didn't publish one connector: they published **nine** — Oura,
WHOOP, Garmin, Strava, Fitbit, Withings, Apple Health, Polar, nutrition — under a
registry with its own quality standard, plus an installer that configures them
all in one command.

It's worth looking at because **half of that constellation already exists here**:
`oura-mcp`, a Withings MCP, `cotejo` for blood biomarkers, and `panel-salud` as
the place where it all meets. The difference is that theirs share installation,
documentation and a declared stance; these are four loose repositories solving the
same problem with the same judgment.

And there's something none of the nine has: **a position on method**. Theirs
promise "insights" and template-generated advice from a score, without saying how
much that score swings on its own. A registry of connectors that hand over raw
data and send the analysis where the method can be cited would be a direct answer,
and one of the few defensible ones.

The technical bridge was already pointed out by `echocharlie`: **compose by
date**. Having `oura-mcp` and the Withings MCP speak `YYYY-MM-DD` with the same
key scheme is what lets a model cross them without either one analyzing anything.

---

## What the end-to-end audit found

The 124 tests exercise functions. None started **the process**. And the ugliest
way an MCP server fails isn't returning wrong data: it's failing the *handshake*,
or writing something to stdout that isn't JSON-RPC. Both look identical from the
client — a server that "doesn't show up" — and no function test catches either.

`tools/smoke_stdio.py` starts it for real and speaks stdio to it. On the first
run it found that **the server was announcing itself as `oura 0.1.0`** with
`pyproject.toml` at 0.2.0: the number was hand-written in two places. It now comes
from `importlib.metadata`, and a test ties together the six version declarations
in the repo.

Along with it, `tests/test_coherence.py` pins what the documentation can't
contradict: the `mcp-name:` line the registry demands, the privacy policy the
directory demands, and the claims that expired once — "four tools", "the most
complete one doesn't paginate" — so they can't come back.

And one that caught itself: the first version of that test used `tomllib`, which
is Python 3.11, while `pyproject.toml` declares 3.10 as the minimum. It would have
broken CI on precisely the oldest version we claim to support. The whole tree is
now checked against 3.10 grammar.

---

## Three bugs that only surfaced on rereading the secret-handling code

The credentials and authorization modules were written straight through and
hadn't been reread. All three are the same class: cases a real user produces
without trying.

**1. A favicon killed the entire authorization flow.** The callback listener
served *one* request. A real browser doesn't send one: it asks for
`/favicon.ico` on its own. That one took the turn, the server closed, and the
good callback got *connection refused*. From outside it looked like "no callback
arrived in 300s", with no clue why. Reproduced and fixed: it now serves until
something reaches `/callback`.

**2. An OAuth code containing `=` was rejected.** Codes are base64url and carry
`-`, `_` and `=` padding perfectly normally. The heuristic looked for `=` or `/`
to decide whether the input was a URL, so `abc=` came back as "that carries no
`code`" — to someone who pasted exactly what they were asked for. It's now decided
by shape (`http://` or `?`), not by characters.

**3. `OURA_CREDENTIALS=cred.json` crashed.** A bare relative path left the
directory as an empty string and blew up with `FileNotFoundError: ''`. It would
also have made credentials depend on the directory the server was started from,
which in an MCP client is not the one you think. It's now normalized to absolute.

And a fourth, minor but ugly: saving to the keychain left the old file on disk
carrying a dead refresh token that a later load would never read. A secret nobody
uses is still a secret somebody can read. It gets deleted.

---

## And a fourth exit from the loop, which nearly got away

The pagination loop had two exits: an empty `next_token`, or the page cap. It was
missing the classic one: **if Oura repeats the same `next_token`, that's a
cycle.**

Without detecting it, the client made **50 identical requests**, returned 50
copies of the same record, and the warning said "shorten the range" — useless
advice, because shortening doesn't stop the API from repeating itself. It also
burned 49 requests against a rate limit Oura announces in no header. It now stops
on the second one and calls it by its name: `pagination_cycle`, not `truncated`.

It would have been ironic to carry that in the very file that is the project's
reason to exist.

Along the way, two response shapes that were being treated too generously. The
code wrapped the whole body as a record whenever `data` wasn't a list — correct
for `personal_info`, which isn't wrapped, but it turned an unexpected
`{"data": {...}}` into "one record" shaped like `{"data": …}` that looks
legitimate. It's now told apart by the **absence** of the key: if `data` arrives
and isn't a list, the shape changed and it says so rather than inventing an
interpretation.

---

## What nobody was measuring: response size

All night was spent on the data's correctness and never on its volume. Measured
against the real API, this is what a model actually receives:

| Query | JSON | CSV | Savings |
|---|---|---|---|
| Catalog (`oura_collections`) | 1,764 | — | — |
| `daily_sleep`, 30 days | 7,296 | 6,608 | 10% |
| `sleep` detailed, 30 days | 120,571 | 100,852 | 17% |
| **`daily_activity`, 30 days** | **251,814** | 195,643 | 23% |
| `heartrate`, 1 day | 139,720 | 63,841 | 55% |

Two corrections come out of this.

**The README's "56% less" was the best case, not the typical one.** CSV savings
range from 10% to 55% depending on how much nesting a collection carries. Quoting
only the best number is the kind of thing this repository holds against others.
Fixed: the range is given.

**And 30 days of `daily_activity` is a quarter of a million characters** — some
60,000 tokens — with nothing warning about it. 92% of each record is a single
field, `met`, a per-minute MET series. Asking for three columns with `fields`
brings those same 30 days down to 5,016 characters: **99% less**.

The response now carries `large_response` past 50,000 characters, naming the
field that dominates and its share. **It trims nothing on its own** — that would
be under-delivering, exactly what this package exists not to do — but it stops
spending the asker's context in silence.

---

## The five real questions, simulated

The code was heavily reviewed and the answers were correct. What was missing was
asking whether **a model can answer with them without guessing**. The five a user
actually asks were simulated over stdio.

Four came out fine. The fifth revealed the largest remaining hole, and it's this
repository's thesis turned against us:

> "how did I sleep last night?" → `{"collection": "daily_sleep", "n": 0, "pages": 1}`

That doesn't distinguish between **four things that lead to opposite
conclusions**: you weren't wearing the ring, the ring hasn't synced, you asked
for a future date, or your token lacks that scope. A model receiving `n: 0` will
answer "you didn't sleep" with complete confidence — and `n: 0` is the most
common answer to the most common question.

Handing over an empty result without explaining it is precisely "under-delivering
without warning", committed by us on the primary interaction.

The response now carries `empty`, which **doesn't guess** which of the four it is:
it lists what can be checked without going to the network — whether the range is
in the future, whether it reaches today and therefore may not have synced, whether
the credentials lack the scope that collection needs — and states that "no data"
isn't "it didn't happen".

The scope part required a new table, `SCOPE_OF`: which OAuth permission each
collection needs. Without it, an `n: 0` caused by a missing permission is
indistinguishable from one caused by missing data.

**And the two-step join works.** "How was my heart rate during yesterday's
workout?" requires requesting `workout`, taking `start_datetime`/`end_datetime`
and using them on `heartrate`. The formats line up with no conversion — verified —
but nothing told the model so. It's now in the server instructions, along with the
other three things it can't guess.

---

## The default that answered a question nobody asked

Oscar read the sample-data checkbox in the `.mcpb` and asked the right question:
is that left on by default — what about someone who doesn't read?

The checkbox turned out to be the smaller half. `oura_check` announced that
sandbox data was synthetic; **the queries did not.** So a fresh install, in the
default configuration, answered "how did I sleep?" with a score of 73 out of
Oura's made-up data, and nothing in the response said whose data it was. A model
has no way to know, and would report it as the person's own.

That is this repository's thesis — an answer that looks right when it isn't —
committed by us, against our own users, on the default path.

**The fix is in band, not in the documentation.** Every sandbox response now
carries a `synthetic` key naming what it is and what to do next. Documentation
is where warnings go to be skipped; a key in the payload is where a model must
read it.

**The default stays on**, and now it's defensible. Turned off, a stranger with
no registered Oura application gets an error on their first question instead of
a working demonstration. Turned on and marked, the first question demonstrates
the tools *and* names the next step. What changed is that "on" is now tied by
test to the marker existing — `test_the_sample_data_checkbox_warns_in_its_title`
fails if the default flips without someone revisiting this.

### Two more found while fixing it

**Declining the authorization prompt killed the server.** `cancel()` rejects a
promise nobody awaits — the caller throws its own error instead — and Node treats
an unhandled rejection as fatal. No assertion caught it; vitest reporting
unhandled rejections as errors did. Saying "no thanks" should not take the
process down.

**Twelve dead commands in the documentation.** The CLI flags were translated with
everything else — `--autorizar` → `--authorize`, `--revisar` → `--check`,
`--olvidar` → `--forget` — and the README, `llms.txt`, `AGENTS.md` and a
`package.json` script went on citing the old ones. The tool-parameter rename got
recorded in the changelog; the flag rename didn't, so nothing was looking. Every
flag quoted in the documentation is now checked against the list the CLI accepts,
and the two CLIs are checked against each other.

### What the build script was hiding

`npm install --silent` swallowed a corrupted-cache error, so the build exited 1
after printing "installing production dependencies" and nothing else. Same family
as everything above. It now prints npm's own output and names the fix.

And the bundle verification was too weak to catch any of this: it completed a
handshake, which the unmarked build did perfectly. It now issues a real
`tools/call` and fails if the sample data comes back unlabeled.

## State at the close

**Done:** v0.2 (eight fixes), v0.3 (full OAuth2), v0.4 (Claude Code plugin,
discovery files, measured binary, TypeScript port). 124 tests, none touching the
network.

**Nine real bugs**, all found by rereading code that had already been called
done, and all of the same family — *it looks like it worked*:

| | |
|---|---|
| Inconsistent `end_date` + UTC skew in `workout` | asking for one day returned zero |
| `latest` and `fields` silently ignored by Oura | you asked for one, you got everything |
| A favicon killed the authorization flow | "no callback arrived" |
| An OAuth code with `=` was rejected | to whoever pasted what they were asked for |
| A relative `OURA_CREDENTIALS` crashed | `FileNotFoundError: ''` |
| A repeated `next_token`: 50 identical requests | and the wrong advice |
| The server lied about its version | 0.1.0 with pyproject at 0.2.0 |
| A typo'd flag started the server | it looked hung |
| `personal_info` in the sandbox returned a bare 404 | it looked like everything was broken |

**What wasn't done, and why:** what remains are decisions — the `.mcpb`'s scope —
not pending work.

---

## Execution order — reprioritized 10 August 2026

Rewritten after reading the WHOOP ecosystem and counting the field. The old
order assumed getting listed was the finish line. It isn't.

### The number that reorders everything

**The MCP registry already carries ten Oura servers.** Measured directly against
the registry API on 10 August 2026:

| version | server |
|---------|--------|
| 1.16.0  | `ai.smithery/eliu243-oura-mcp-server` (listed three times) |
| 0.6.0   | `ai.foura/mcp` |
| 0.4.6   | `io.github.davidmosiah/ouramcp` |
| 0.4.1   | `io.github.AntVsl/oura-mcp` |
| 0.3.0   | `io.github.proscar87/oura-mcp` ← this one |
| 0.2.13  | `io.github.YasuakiOmokawa/oura-mcp` |
| 0.2.0   | `io.github.jordanburke/oura-ring-mcp-server` |
| 0.1.4   | `io.github.mitchhankins01/oura-ring-mcp` |
| 0.1.1   | `link.smirnov/mcp-oura` |
| 1.0.0   | `com.sendyouragent/readiness` |

Being in the registry sat near the top of the old list. It is **table stakes**:
everyone is there, several of them for longer and at higher version numbers. A
listing is the cost of entry, not a differentiator, and any plan whose payoff is
"we get listed" is a plan to be tenth.

What is scarce is the **Claude desktop extension directory** — a separate, much
smaller door, and the only one that ends in a double-click.

### 1. Attach the `.mcpb` to a GitHub release · **done, 10 August 2026**

The README sends people to a releases page that is **empty** — verified, zero
releases. The most visible install path in the most-read file leads nowhere.
Everything below is worth less than fixing a broken promise that is already in
front of people. Costs one command.

### 2. Make the first screen of the README say the difference · **done**

The ecosystem scan showed the differentiator is real and invisible.
`jonnyhaynes/whoop-mcp-server` ships `nextToken` **as a tool parameter** — the
model is expected to paginate — and someone comparing ten Oura servers has no
way to tell which ones do that. Ours explains it well below the fold.

The claim has to be the first thing read, and checkable in the time someone
spends choosing: *one local day of heart rate is 1,231 samples across 2 pages; a
client that doesn't paginate returns 81% of them and says nothing.* Measured,
quotable, and nobody else in the field publishes a number like it.

### 3. Submit to the Claude desktop extension directory · **blocked on Oscar**

Now genuinely the highest-leverage listing, precisely because the registry is
crowded and this door is not.

The submission is a Google Form behind a sign-in, so it needs Oscar's account.
Everything it asks for is written and ready; this is the only item on the
roadmap that cannot be finished from here.

### 4. `awesome-mcp-servers` and mcp.so · **done**

- `awesome-mcp-servers` (92k stars): PR
  [#11833](https://github.com/punkpeye/awesome-mcp-servers/pull/11833), filed
  under **Health & Wellness**, which had exactly one entry. Being second in the
  semantically right category beats being the third Oura server buried in a
  400-line Biology section — and their CONTRIBUTING.md fast-tracks agent PRs
  that say so in the title, so it does.
- mcp.so: submitted as [issue
  #3503](https://github.com/chatmcp/mcpso/issues/3503), which is the route their
  form actually feeds.
- glama.ai already indexes the repository — verified, no submission needed.

### What the release itself turned up

Shipping 1 and 2 produced 0.3.1 rather than a doc change, because writing the
README lead honestly meant reading what the code did, and it didn't match.

The lead now poses a test — *does it take `next_token`, a `cursor`, or a `limit`
as a tool parameter?* — and applies it to this server too. Checking that, it
turned out `continue_from` handed back Oura's opaque token while **no parameter
accepted one**. The response told the model to continue from a value it had
nowhere to put. It is now the last day reached, which works with `start`.

And eight retired Spanish key names were still documented — `campos_ignorados`,
`ciclo_de_paginacion`, `descartados_fuera_de_rango`, `respuesta_grande`. Worse
than the dead CLI flags found earlier: a flag fails loudly, while a key that
never arrives just looks like the condition never happened.

Both were found by writing a claim aimed at strangers and then checking whether
it was true. That is worth more than the marketing.

### Settled — removed from the roadmap, not deferred

**Embedding OAuth app credentials.** Every WHOOP server examined makes the user
register their own application. That is what this category looks like when the
vendor requires registered apps. It was the last piece of install friction and
it is not ours to remove. What remains is keeping that one step short and
impossible to get wrong, which the manifest already does by spelling out the
trailing slash.

**More tools, and server-side analysis.** `thebriangao/totem` runs 47 tools and
still computes no trends, averages or correlations. Tool count was never what
forces analysis into a server, so growing ours wouldn't threaten the line we
drew — and wouldn't help either. Three tools stay.

**Chasing stars.** The most-starred WHOOP repository (`OpenStrap/edge`, 427
stars) is about using the hardware *without a subscription*. Oura doesn't
paywall its API, so there is no equivalent lever here. The attention in this
category is for escaping a fee; mistaking it for interest in MCP servers would
send us building the wrong thing.
