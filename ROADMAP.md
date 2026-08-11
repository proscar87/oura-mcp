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

## The 20-hour audit — round 1

Started 10 August 2026. Brief: find what's missing, what isn't being exploited,
and iterate. Publishing and third-party repos are out of scope by standing rule.

### A rate limit that recovered used to leave no trace

Oura refuses with 429 and this client retries, bounded. When the retry
**succeeds**, nothing said it happened: the caller waited, the answer came back
clean, and the response looked identical to one that was never refused.

That is not the same bug as the four this package was built for — the data is
correct. It's a fact about the **next** query rather than this one. Oura sends no
rate-limit headers on successful responses, so being refused is the only signal a
client ever gets that it's near the ceiling, and throwing that signal away means
a model asks for another fifty pages and that request is the one that fails.

Responses now carry `rate_limited` when a retry recovered: how many refusals,
how long was spent waiting, that the data is complete, and to make the next
range smaller. In both implementations, checked against each other by the parity
test — which is what caught TypeScript missing it.

### The README documented parameters that no longer existed

The parameter table still read `dia`, `inicio`, `fin`, `campos`, `ultimo`,
`formato`, and `llms.txt` asserted "parameter names are in Spanish because the
codebase is." Both false since 0.3.0.

Oscar pasted that table back as evidence something was wrong. It was — and not
only where I said. I attributed it entirely to his stale 0.2.0 install, which was
true of the running process and incomplete as an answer: the documentation was
independently wrong, and would have stayed wrong after he updated.

Neither existing guard could see it. The flag test only inspected `--flags`; the
key test only inspected retired response keys. **Parameters were a third
vocabulary with nobody watching it.** The new test reads the live tool schema, so
a rename that skips the docs now fails in CI instead of in someone's terminal.

Three vocabularies, three lessons, one shape: translating a codebase breaks
references that no compiler checks, and each class of reference needs its own
guard because none of them generalize.

### Round 2: simulating the questions found two more

Ran the three questions a person actually asks — worst night of the month,
did I sleep better on training days, compare January against February — against
the sandbox, and read what a model would receive.

**`fields` as a comma-separated string was rejected with a validator dump.**
Declared `list[str]`, a model sending the very natural `"day,score"` got:

    Input should be a valid list [type=list_type, input_value='day,score']
    For further information visit https://errors.pydantic.dev/2.13/v/list_type

Technically correct, and a link to a library's website is not an answer — it is
precisely the kind of response this package exists to stop shipping, on what is
almost certainly the most common mistake anyone will make with this tool. Both
implementations now accept either form. No Oura field name contains a comma, so
splitting is unambiguous. The response says `fields_split` when it happened,
because silently reinterpreting someone's input is the other half of the same
sin.

**`discarded_out_of_range` was a bare number that read as data loss.** It fires
on essentially every dated query — two extra days are always requested on each
side and always trimmed — so it reports the safety margin working, not a
problem. `discarded_out_of_range: 3` invites "3 of your records were thrown
away", which is the opposite of true, and a warning that fires every single time
stops being read regardless. It is now a sentence that says it is normal.

### Round 3: reading the errors as a model would

Sent the server the mistakes a model actually makes and read every reply. Most
were good — the invented collection name comes back with all nineteen listed,
`latest` where it doesn't apply explains why, a backwards range says so. Two
were not.

**«What was my heart rate on January 1st» returned nothing.** `heartrate` and
`ring_battery_level` take `start_datetime`/`end_datetime`, and a bare
`YYYY-MM-DD` went through untouched:

    start_datetime=2026-01-01&end_datetime=2026-01-01

An interval of no duration. Oura returned zero records, and the empty-reason
said *"the query succeeded; Oura has no records in that range"* — blaming Oura
for a window this client had emptied itself. The most natural question anyone
would ask of a heart-rate collection, answered with a confident lie.

This package's own thesis, committed by this package, with the explanation
pointing away from the cause. A bare date now means the whole day.

One thing deliberately NOT claimed: whether Oura's `end_datetime` is inclusive.
It wasn't measured — the sandbox is a generator, not a filter, and measuring it
against a real account means handling someone's health data to settle a detail
the conservative choice already covers. So the end is `T23:59:59`, and the
comment says it's a hedge rather than a finding. Being wrong that way costs one
second; the other way contaminates a day.

**The catalog returned a key called `que_trae`,** and the two implementations
described themselves differently — Python `date_range`, TypeScript `dateRange`,
both leaking their internal spelling into public output. The same server
answered differently depending on which one you installed.

That is a **fourth vocabulary**: after CLI flags, response keys and tool
parameters, the tool *return* values had nobody watching them either. Each guard
was written for the class of reference that had just broken, and none of them
generalized. The new tests cover both the Spanish leak and the catalog parity.

### The empty capabilities: checked, not a problem

We advertise `prompts` and `resources` and expose none. Verified directly:
`prompts/list`, `resources/list` and `resources/templates/list` all return clean
empty arrays — the capability says "I implement this method", and we do.

But there was something worth taking. `oura://collections` is now a **resource**
carrying the same catalog: static, no network, no credentials, no health values.
The most likely mistake on this server is inventing a collection name — the
error for it exists and lists all nineteen, which is an admission that it was
expected. A resource puts the list in front of the model *before* the mistake
rather than after it, without a round trip.

### Round 4: a lock on the whole surface, instead of one guard per break

Four classes of name had broken one at a time — CLI flags, response keys, tool
parameters, return values — and **every guard was written after the class it
watches had already broken.** None generalized. Guessing which class breaks
fifth is a losing game, so `tests/test_public_surface.py` stops guessing and
pins all of it: tool names, every parameter of every tool, every response key in
both implementations, the CLI flags, the resource URIs.

Rename anything a client can see and it fails until someone writes the new name
down deliberately. That cost is the point — these names are a promise to people
who already installed the thing, so a rename should be a decision rather than a
refactor. Verified by breaking it on purpose: renaming `synthetic` to
`sintetico` failed two tests immediately.

### Four more Spanish messages, in the worst possible place

The sweep found user-facing error strings that survived the translation: `no se
pudo alcanzar Oura` in Python, two more in TypeScript, and a Spanglish
`no hay refresh token; hay que authorize de nuevo`. All of them are read by
someone who is **already stuck**. Comments and internal names can lag; a message
cannot.

**And one deliberate non-translation.** The keychain account name is
`credenciales` and stays that way. It is a storage key, not a message: anyone
who authorized before the translation has their refresh token filed under that
exact string, and renaming it would orphan those credentials silently — `load()`
finds nothing and asks them to authorize again with no explanation, while the old
secret stays in their keychain forever. There is now a test whose job is to stop
a future sweep from "fixing" it.

### Where coverage was thin, and where it didn't matter

78% overall, but the number was not the finding. `credentials.py` sat at 69% and
the untested lines were the keychain path and the token-exchange error handler —
the code that stores and erases someone's OAuth secret. That is where the sweep
above started, and what it turned up.

### A trap worth writing down

While verifying the surface lock bites, the restore afterwards silently didn't
take: `synthetic` and `sintetico` are **the same length**, and the restore landed
in the same second as the mutation, so Python considered the cached bytecode
valid and kept running the mutated module. Four tests failed against a source
file that was, on disk, correct — and `git diff` showed nothing.

Every instinct said "the code is fine, the tests are wrong". The code *was* fine.
What ran wasn't the code.

### Round 5: the instructions never mentioned whose data it was

The server's instructions travel in every session and are the only text a model
reads before deciding anything. They told it to read `empty`, `truncated` and
`large_response` — and **never mentioned `synthetic`**, in the configuration
that ships turned on.

The marker landed in every response two rounds ago. Nothing told a model it
outranked the rest. So it now goes AHEAD of the four rather than among them,
because those four are about whether the data is complete and this one is about
whose it is. A wrong answer about completeness is incomplete. A wrong answer
about ownership is fiction presented as someone's health.

### The lock built to be general already had a blind spot

Round 4 pinned the public surface so no name could change unnoticed. One round
later, `_oauth_state` was found returning `{"credenciales": ...}` — a Spanish key
in a user-facing diagnostic — because the lock only read `out[...]` assignments
and this one was written straight into a returned dict literal.

**A guard is only as general as the shapes it knows how to look at.** The lock
now reads literals too, and the test that closes the hole says in its own
docstring that the hole existed.

### Coverage: 78% → 88%, and what it was hiding

The number was never the point; where it was thin was.

`credentials.py` (69% → 92%). The untested code was the keychain path and the
token-exchange error handler — where someone's OAuth secret is written, read and
erased. The tests that close it check the two things that actually cost
something: that a keychain save **deletes the file**, because `load()` prefers
the keychain and an orphaned file is a consumed refresh token sitting readable on
disk forever; and that a keyring which imports but has no backend falls back to
the file instead of taking the session down.

`__main__.py` (21% → 88%). The branch that mattered is `--forget`: a dispatch bug
would print `{"forgotten": true}` over an untouched refresh token — this
package's own thesis aimed at the one command whose whole job is to be believed.

`server.py` (55% → 64%). `oura_check` is what someone runs when they are already
stuck, and it now has tests proving it leaks neither the token nor a single
health value. The rest of the gap is network paths, and the rule that CI never
touches the network is worth more than the percentage.

### A comment that argued against a feature we shipped

`__main__.py` asserted that OAuth "belongs in the terminal, NEVER inside the
server", because a server speaking over stdin/stdout can't open a browser. That
was true when written and stopped being true in 0.3.0, when URL elicitation made
the server do precisely what the comment called impossible. Comments age like
READMEs, with the difference that nobody rereads them.

### Round 6: the least-tested copy was the one most people will run

Python had 187 tests, TypeScript 48. Most of that gap is legitimate — document
coherence doesn't need testing twice — but one part of it was not:

**`credentials.ts` had no tests at all.** Python had 28 for the same job. That
is the code which writes, reads, rotates and erases someone's OAuth refresh
token, and TypeScript is what goes inside the `.mcpb` — the install path being
pushed hardest. The least-tested copy was the one most people would run, of the
most dangerous code in the package.

Seventeen tests now cover it, and they were checked by **breaking the thing they
claim to protect**:

| broken on purpose | noticed |
|---|---|
| file mode 0600 → 0644 | no — and correctly: an explicit `chmod` after the write makes it redundant. Removing *both* is caught. |
| `save()` before returning, in `refresh()` | yes |
| the "somebody else already refreshed" race | yes |
| temp-file cleanup on failure | **no** |

That last one was a hole in the test, not the code. The first version broke
`asJson()`, which throws **before** anything is written — so there was never any
debris to look for and it passed without exercising the cleanup at all. A test
that looks like it checks something and doesn't, inside the suite of a package
whose entire subject is answers that look right.

Python's equivalent was written correctly — it fails `os.replace`, after the
temp file exists. I ported the intent and not the mechanism.

### A credentials file the documentation named wrongly

Both implementations store at `~/.config/oura-mcp/credenciales.json`, and they
agree, which matters: if they had drifted, `oura-mcp --authorize` from PyPI would
leave the `.mcpb` reporting «no credentials» — two halves of one product refusing
to see each other's work. There's a test for that now.

The name stays in Spanish for the same reason the keychain account does: it's a
storage path, and renaming it orphans anyone who authorized earlier.

What was wrong is that two places **named a file that doesn't exist**. The
`.mcpb` manifest — the text someone reads in Claude Desktop's settings while
configuring this exact path — and `SUBMISSION.md`, which is a factual claim about
where credentials live, written for a directory reviewer. A privacy statement
naming the wrong file is worse than a stale README.

### Three warnings the README never mentioned

`synthetic`, `rate_limited` and `fields_split` were all added by this audit, and
all three reached `llms.txt` while none reached the README. llms.txt is read by
models; the README is read by people deciding whether to install. Documenting a
warning in only one means half the audience meets it for the first time in a
live response.

### Round 7: a green suite and a suite with teeth are different claims

255 passing tests say the tests pass. They do not say the tests would **fail if
the product broke**, and after six rounds of adding tests it was worth finding
out which claim was actually true.

So every core guarantee was broken on purpose — the reasons this package exists —
and the suites were run against the sabotage. `tools/mutate.py` now does it on
demand.

Twelve of twelve held in Python. TypeScript had two that didn't:

**`ignored_fields` never reached the response, and nothing noticed.** The helper
`ignoredFields()` had its own test; the line attaching its result to the response
had none. Deleting that line broke nothing. The function worked, the wiring was
unguarded — and a warning that never arrives looks exactly like a query with
nothing to warn about. Python had the end-to-end test. Same asymmetry that left
`credentials.ts` with no tests at all.

**A `Secret` has three ways out and only two were watched.** `toString` and
`toJSON` were covered. `nodejs.util.inspect.custom` was not — and that is the one
that fires on `console.log` and **inside a stack trace**, which is exactly how a
token leaked in this project once. Both halves now check every route a string can
take out of the object, including a formatted traceback.

Along the way: the TypeScript `Secret` printed `<secreto de N characters>` —
Spanglish, and different from Python's `<secret, N characters>`. That string
shows up in logs and traces, which is where someone looks when a token is
misbehaving, so the two halves of one product were describing it differently. And
its public property was `largo`.

### The non-finding that matters as much

The run also reported a mutant that survives **correctly**: changing the file
mode on `writeFile` in `credentials.ts` goes unnoticed because an explicit
`chmod` after it makes that argument redundant. Removing both is caught.

Defense in depth and a coverage hole look identical from outside the code. **A
surviving mutant is a question, not a verdict** — which is why the tool prints
"read the code before adding a test" rather than a score, and why chasing a
number here would have produced a test asserting something already guaranteed
twice.

### Round 8: a lone carriage return, and a lock with its key on the door

**The `state` was never checked for being unpredictable.** Every existing test
verified that a *mismatched* `state` is rejected, and the constant-time
comparison had teeth. Nothing verified that an attacker couldn't simply know the
right one — which is the only thing `state` exists for. Replacing
`secrets.token_urlsafe(24)` with a constant passed the entire suite. A fixed
state, faithfully and constant-time compared, is a lock with its key printed on
the door. Both halves now check that twenty authorizations produce twenty
different values, each long enough not to be guessed.

**CSV: a real bug, found where it was expected to be.** `tag` and `enhanced_tag`
carry `comment` — text the person typed — so commas, quotes and newlines are not
edge cases there, they're Tuesday. A CSV that escapes them wrong doesn't fail; it
shifts every column right, and the numbers that come out are another field read
under this one's name.

Python was correct: it uses the standard library. **The TypeScript one is
hand-written**, which is exactly why it needed a test the other didn't — and it
had a gap:

    Python:      2026-01-01,"a\rb",73
    TypeScript:  2026-01-01,a\rb,73

A **lone carriage return**, with no newline after it. The escaping regex listed
`"`, `,` and `\n` and not `\r`; Python quotes it because its `csv` module counts
`\r` as part of a line terminator. Readers that end a row on a bare `\r` — Excel
among them — split the row there and shift everything after it. Rare, silent, and
wrong in the way this whole package is about.

Both are now checked against a strict reader written for the test rather than the
one under test, across six kinds of hostile value, asserting that a **number**
stays in its own column — which is the thing that actually harms someone.

And the CSV escaping is in `tools/mutate.py` now, because it earned its place.

### Round 9: the table that answered the question, at the one moment nobody asked it

`SCOPE_OF` exists in this package for exactly one purpose, stated in its own
docstring: telling *«there is no data»* apart from *«you didn't grant that
permission»*. The two look identical from outside — both arrive as nothing — and
they lead to opposite conclusions.

The empty path consulted it. **The 403 path did not**, and a 403 is Oura
*answering that question out loud*. It replied:

    Oura responded 403: Forbidden

The status code, restated. Someone asking for their workouts with a credential
that lacks the `workout` scope got a number and a word, and no way to tell that
from an outage or a bad date.

Now:

> Oura refused `workout` with 403. This collection needs the `workout` scope and
> your credentials don't have it (you granted: daily). Run `oura-mcp --authorize`
> again and approve it.

With a personal token the granted list isn't readable, so it says which scope the
collection needs and stops short of claiming what was granted. Saying nothing
beats guessing at somebody's permissions.

A 401 deliberately still talks about the token and never about scopes: expired
and unauthorized are different problems with different fixes, and blurring them
sends someone to re-approve permissions they already have. Both implementations
now say *«Did the credential expire?»* — they had drifted to different wordings
of the same sentence.

### Checking a check

The TypeScript test for that last point is a **negative** assertion —
`rejects.not.toThrow(/scope/)` — and negative assertions are the easiest kind to
write in a form that can never fail. So it was verified the same way everything
else has been this week: the word `scope` was inserted into the 401 message on
purpose, and the test caught it.

### Round 10: two queries at once could lock you out of your own account

The most dangerous bug found so far, and it was **reproduced before it was
fixed**.

Oura's refresh token is single-use: the moment it is exchanged, the one you held
is dead. MCP tools run concurrently. So two queries arriving after the access
token expired started two exchanges of the **same** token:

    token endpoint calls: 2
    query 1: fulfilled
    query 2: rejected -> Oura rejected the exchange (400): Refresh token already used.

One of two identical, correct queries fails with a message the person cannot act
on, that reads like corruption, about a query that had nothing wrong with it.

**A recovery already existed** — on failure, reload and use whatever another
refresher saved — and its docstring even names this scenario, "two MCP tools
called in parallel". But that recovery is **itself a race**: it only works if the
winner finished writing before the loser finished reading. Knowing about a race
is not the same as closing it.

Both halves now do one refresh at a time — a lock in Python, a shared promise in
TypeScript. Same reproduction afterwards: **one** call to the token endpoint,
both queries answered.

Three things that took care to get right:

**The re-read under the lock has to be narrow.** The first attempt short-circuited
on "what's on disk looks valid", which turned `refresh()` into a no-op for every
ordinary caller — seven tests caught it. The correct test is *different from the
one I am holding*: that means somebody else refreshed, and exchanging mine would
spend a token that is already dead.

**Sharing the failure is deliberate.** If the exchange genuinely cannot succeed,
both callers hear the real reason — `Invalid client_id.` — rather than one of
them hearing "already used", which points at the wrong problem entirely.

**It must not wedge.** A shared promise that is never cleared would poison every
refresh for the life of the process; there is a test that one failure is followed
by a working refresh.

The cross-process case — the CLI and the server at once — still relies on the
recovery, because no lock in one process can see another. That limit is stated in
the code rather than left to be discovered.

### Round 11: advice that cannot be followed

The cold start — what someone meets when the credentials file isn't what we
expect — was probed with five broken states in both implementations: empty,
blank, valid-JSON-wrong-shape, a directory in its place, and unreadable.

Nothing crashed. Every one arrived as a readable error rather than a traceback,
which is what the earlier rounds were for. But two of them gave **advice that
cannot be followed**:

    the credentials file could not be read (PermissionError).
    Delete it and authorize again: …

Deleting needs permission too. Someone whose file is unreadable tries the
suggested fix, fails at that as well, and ends up further from an answer than
when they started. Same for a directory sitting where the file should be: `rm`
without `-r` won't remove it.

Both now say what's actually wrong and what would actually help — check the
ownership and mode for a permission problem, remove the directory for the other.
And TypeScript now names the cause the way Python already did; it was throwing
the same sentence for every failure.

### Every number, re-checked

The numeric claims are this package's argument, and nobody had re-read them in a
week of changes. Everything checkable offline still holds: 19 collections,
1,000 of 1,231 is 81%, 1,231 needs exactly two pages, the bundle is 3.1 MB.

The measurement itself can't be re-run here — it needs a real account, and
handling someone's heart rate to re-check a README is not a trade worth making.
What *can* be checked is that the three numbers still describe each other, and
that is now a test: the headline is quoted in five places, and someone correcting
one of them and not the others would produce a paragraph arguing against itself.

There's also a test that `~37,000` keeps its tilde. It's extrapolation —
1,231 × 30 is 36,930 — and every other number in that paragraph was measured. A
reader has no way to tell them apart if the mark that says so gets tidied away.

### Round 12: the handoff document sent the next reader to directories that don't exist

Three things were checked and found sound, and are recorded here as negative
results because knowing what was looked at is worth as much as knowing what was
found:

- **Malformed stdio.** Invalid JSON, an unknown method, an unknown tool, wrong
  argument types, missing required arguments. Nothing crashed, the server stayed
  alive through all of it, and each got a proper answer — `-32601` for the
  method, `isError` for the tool, a validation message for the types.
- **Undeclared collections.** Sixteen plausible names probed against Oura's
  sandbox. Every one 404s except the one already declared. `check_drift.py`
  covers the other direction.
- **`llms.txt`** carried every response key. It was missing only the new
  resource, which is now listed.

Two real findings:

**The «no credentials» message was written for someone with a terminal.** It
offered `OURA_SANDBOX=1` and `oura-mcp --authorize`. Whoever installed the
`.mcpb` has **no `oura-mcp` command anywhere** — the bundle ships node and a dist
directory, nothing on the PATH — and `OURA_SANDBOX=1` is a checkbox in their
settings, not an environment variable. Both instructions were unfollowable for
exactly the audience the flagship install path creates. Same shape as round 11:
a fix that cannot be applied is not a fix. The message now names both routes, and
quotes the checkbox by its real title so renaming it in the manifest breaks a
test rather than someone's afternoon.

**And `AGENTS.md` — the file whose entire job is to orient whoever arrives
next — was stale in the way that matters.** It sent the reader to
`herramientas/check_drift.py` and `.github/workflows/deriva.yml`: a directory
and a workflow renamed during the translation. **Dead commands in the one
document written to be followed.** It also listed the `.mcpb` as pending work,
claimed 124 tests, and never mentioned `tools/mutate.py`.

It now names paths that exist — verified by a test that walks every repo-relative
path it mentions — records the four decisions this week produced that must not be
reverted, and leads its testing section with the instruction to run the mutation
tool before believing a green suite.

### Round 13: the `state` check crashed the server it was defending

The code claims, in a comment, that the callback listener starts **before** the
client is told to open anything — because a fast user reaching the callback with
nothing listening produces a failure that looks like Oura's rather than ours.

Reading the statement order doesn't prove it. `listen()` is asynchronous and the
socket doesn't accept until its `listening` event fires, so the claim could be
false while the code reads correctly. It was tested by connecting to the port
from inside the elicitation callback — the exact instant the client is being
told — and **the claim held**.

The test crashed the process anyway.

A callback with a mismatched `state`, arriving while the prompt is still open,
rejected a promise **nobody was awaiting yet**: the flow had started the listener
and moved on to waiting for the client's answer. In Node an unhandled rejection
kills the process.

Which inverts the entire purpose of the check. `state` exists because **any page
the user visits can hit `localhost:9876`**, and rejecting those callbacks is the
whole defense. Crashing on them made the defense the vulnerability — a denial of
service any web page could trigger, against the MCP server, at the one moment the
user is mid-authorization.

The fix is one line and it is about **when**, not whether: the rejection is
claimed at creation instead of whenever someone gets around to awaiting it.
Attaching a handler marks the original as handled without consuming it, so the
`await` further down still sees the rejection and still throws.

A narrower version of this same fix was written earlier for the declined-prompt
path. That one treated the symptom it had seen; this window was always the real
shape of it.

**Python was never affected** — its callback wait is synchronous, raises, and the
process lives. This is an async-language hazard, and TypeScript is the
implementation inside the `.mcpb`. The half that ships had the bug.

### Round 14: the comments are hypotheses, and one of them was wrong

Round 13's lesson generalized: **an assertion a comment makes about its own code
is an untested claim.** It reads like a fact and it's the opinion of whoever
wrote it, possibly years and several refactors ago. So every "never", "always",
"before", "atomic", "cannot" in both codebases was collected and the testable
ones were tested.

Four held, and are now known rather than assumed:

- **«The listener waits for THE CALLBACK, not the first request.»** A real
  browser asks for `/favicon.ico` on its own; serving one request would let the
  favicon take the turn and the real callback get *connection refused*.
  Verified with favicon, `/`, and Chrome's devtools probe ahead of the callback:
  all 404, callback delivered.
- **«`keyring` is NEVER a dependency.»** Absent from both dependency
  declarations.
- **«All three tools are read-only, and that isn't a promise.»** No POST, PUT or
  DELETE anywhere near the data API.
- **«The path is ALWAYS absolute.»** A bare `OURA_CREDENTIALS=cred.json`
  resolves against the working directory in both.

One was false, and it was the same shape as round 13:

    catch { /* failing to open isn't fatal: the URL was already printed */ }

**`spawn` does not throw when the command is missing.** It emits an `error`
EVENT, so that `catch` caught nothing — and in Node an `error` event with no
listener is an uncaught exception. On any machine without `xdg-open`, which is
most minimal Linux installs, **asking to authorize killed the process** instead
of printing a URL. The call site marks the call `void`, so a rejection had
nowhere to go either; both routes out were open.

Two crashes in two rounds, both in TypeScript, both from a promise or an event
nobody was listening to, both in the half that ships inside the `.mcpb`. Python
was safe in both: `webbrowser.open()` catches `OSError` internally, and its
callback wait is synchronous. **This is an async-language hazard and the audit
should have gone looking for it as a class, not found it twice by accident.**

### Round 15: sweeping the class instead of tripping over it again

Rounds 13 and 14 each found a process crash in TypeScript, both from a promise
or an event nobody was listening to. Finding the same class twice by accident is
not auditing. So this round enumerated it: every `EventEmitter` created
(`createServer`, `spawn`, `createInterface`, `listen`), every promise created and
awaited late or marked `void`, every async callback handed to an API that doesn't
await, every timer with an async body.

Most of it was already sound. The HTTP server has an `error` listener, the child
process got one last round, no timer body is async, and the success path clears
what it armed.

**One was broken, and it's the same idea from the other side.** The `error`
handler rejected and left everything running:

    error reported in 2 ms
    …still alive after 25 s

An occupied port — something else on 9876 — printed «could not listen on port
9876 (EADDRINUSE)» in two milliseconds and then **held the process open for the
full five-minute timeout**. The success path clears the timer; this one didn't.
From outside: an error message, and a terminal that never comes back.

The report was right and the behaviour was wrong. **An error has to stop things,
not only describe them** — which is this package's subject, applied to itself
from an angle the previous fourteen rounds hadn't looked from.

Closing the server needed a guard too: closing one that never bound emits another
`error`, straight back into the same handler.

### Two clean results, and one durable change

`--authorize --manual` with **stdin closed** — a script rather than a person —
exits in about a second instead of waiting forever on a prompt nobody will
answer. And the whole server run under `--unhandled-rejections=strict` answered
every request with **empty stderr**: no hidden rejections anywhere.

That last one is now permanent. The bundle verification runs under
`--unhandled-rejections=strict`, so the next floating promise fails the build
rather than reaching someone mid-authorization. Under the default mode it would
be a warning on stderr that nobody reads.

### Round 16: nothing, and that is the finding

Four classes swept in Python, the way round 15 swept TypeScript, and every one
came back clean:

- **Swallowed exceptions.** All eight `except Exception` blocks are narrow in
  purpose: a version lookup falling back to "unknown", an unreadable error body
  becoming "", a browser that won't open, `keyring` absent. None hides a failure
  that matters.
- **Resource lifecycle.** The HTTP server is shut down, joined and closed on
  *every* exit path, including the timeout and the state-mismatch — which is the
  exact bug found in TypeScript one round earlier, absent here.
- **Port release.** After a timeout, both implementations free the port and a
  retry works. Untested until now, and a plausible way for a second attempt to
  fail for a reason nothing explained.
- **The listener timeout**, in both. Correct, and now exercised rather than
  assumed.

Nothing was found. Under the stopping rule set before the round began, that ends
the audit.

---

## The audit, closed — 10 August 2026

Sixteen rounds over roughly eight hours, fifteen of them producing a real
finding. Every one is written up above with what was broken, what it cost, and
how it was verified.

### What was actually wrong

Ordered by what it would have done to somebody:

| | |
|---|---|
| Two concurrent queries spent the single-use refresh token twice; one failed and could lock the account out | round 10 |
| A callback with a wrong `state` — which any web page can send — **crashed the server** | round 13 |
| A machine without `xdg-open` **crashed the server** when asked to authorize | round 14 |
| "What was my heart rate on January 1st" returned nothing, and blamed Oura | round 3 |
| Sample data reached a model with nothing saying whose it was | rounds 1–2 |
| An occupied port reported in 2 ms and then hung for five minutes | round 15 |
| A lone carriage return shifted every CSV column after it | round 8 |
| A recovered rate limit left no trace, so the next query walked into the ceiling | round 1 |
| A 403 said "Forbidden" while the package knew exactly which scope was missing | round 9 |
| `fields="day,score"` — the likeliest mistake here — answered with a validator dump | round 2 |
| `continue_from` handed back a token no parameter accepts | round 6 |
| Cold-start errors advised deleting a file the person had no permission to delete | round 11 |
| The "no credentials" message assumed a terminal the `.mcpb` user doesn't have | round 12 |
| Four dead vocabularies in the docs: flags, response keys, parameters, return values | rounds 1, 3–5 |
| The handoff document sent the next reader to directories that don't exist | round 12 |

### What changed about how this is tested

Test count went from 124+35 to **215 Python + 87 TypeScript**, coverage from 78%
to 89% — but the counts are the least interesting part.

**`tools/mutate.py`** breaks each core guarantee on purpose and reports which
ones no test notices. It found two with nothing behind them in a repository that
already had 255 passing tests. *A green suite says the tests pass; it does not
say they would fail if the product broke.*

**`tests/test_public_surface.py`** pins every name a client can see. Four classes
of name had broken one at a time, each guard written after the fact and none
generalizing.

**The bundle verification** now completes a handshake, issues a real `tools/call`,
reads the resource, and runs under `--unhandled-rejections=strict` — so the next
floating promise fails the build instead of reaching someone mid-authorization.

### Three habits that produced most of the findings

1. **Test the claims the code makes about itself.** Comments saying "never",
   "always", "before", "atomic" are untested hypotheses. Checking them found two
   crashes.
2. **Sweep the class, don't chase the instance.** The same async hazard was hit
   twice by accident before being enumerated deliberately — and the sweep found a
   third.
3. **A surviving mutant is a question, not a verdict.** One survives correctly,
   because a `chmod` makes the line it targets redundant. Chasing the number
   would have added a test asserting something already guaranteed twice.

### What was NOT reviewed, and why

- **Anything needing a real Oura account.** The headline measurements — 1,231
  samples across 2 pages, 252,000 characters for 30 days of `daily_activity` —
  date from 9 August and were not re-measured. Re-checking them means handling
  someone's heart rate to verify a README, which is not a trade worth making.
  The arithmetic between them *is* now tested.
- **`end_datetime` inclusivity.** Still unmeasured; the code hedges toward losing
  one second rather than contaminating a day, and says so.
- **Cross-process credential races.** One process cannot lock against another.
  The recovery covers it; the limit is stated in the code.
- **Real Claude Desktop installation.** The bundle is verified by running it, not
  by installing it. Gatekeeper's behaviour on a downloaded `.mcpb` is unknown.

### What is Oscar's

1. **Install the `.mcpb`** and confirm macOS doesn't block it. Nothing here can
   test that.
2. **Submit to the Claude extension directory** — a Google Form behind a sign-in.
   `SUBMISSION.md` has every answer written out.
3. **Decide on 0.3.2.** It is unreleased and unlabelled, and carries sixteen
   rounds of fixes including three that crash or lock out. Publishing is
   `git tag v0.3.2 && git push origin v0.3.2`.
4. **The two third-party filings** — `awesome-mcp-servers` PR #11833 and mcp.so
   issue #3503 — are open and awaiting his call on whether they stay.

### Checked and deliberately not adopted

**Argument completion** (`completion/complete`). `oura_query`'s `collection`
takes exactly 19 valid values and a model has to know them or call
`oura_collections` first, so autocomplete looked like an obvious win. It isn't
available: the protocol scopes completions to prompt arguments and resource
template arguments, never tool arguments. Verified against the SDK's own types.

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
