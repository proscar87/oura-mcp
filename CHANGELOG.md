# Changelog

## 0.3.5 — 12 September 2026

**A closed day is now answered from memory, and the response says so.** Ask the
same question twice about a range that ended before today and the second answer
does not reach Oura at all. The rule is the calendar, not a clock: a day that
has already ended cannot gain records, so it is held for the life of the
process; today is never held, because the ring syncs whenever it likes. There
is no expiry to tune and no window in which it can be wrong.

**In memory, never on disk.** The submission to the desktop-extension directory
and the README both state that health data is never written to disk, and a
speed-up is not worth making either of them false. It dies with the process,
and `--forget` clears it — reporting «forgotten» while someone's sleep sat in a
dict would be an answer that is true about what it names and false about what
was asked.

Four things are never held, and each is a way a cached answer becomes a wrong
answer that still looks right:

- **An empty response.** Nothing distinguishes «there is no data for that day»
  from «the ring had not synced when you asked», and holding the second forever
  turns a temporary gap into a permanent one. This is the invariant that made
  caching adoptable at all.
- **A range reaching today or the future.**
- **`latest`**, which asks about now and has no range that can close.
- **A truncated or cycled response**, incomplete by its own admission.

Every hit carries `cached`, for the same reason every sandbox response carries
`synthetic`: «why was that instant?» has to be answerable from the response
itself. `rate_limited` is deliberately NOT replayed on a hit — it describes the
request that happened, and telling someone they are near a limit they never
touched is the same class of false statement as a partial answer presented as
whole.

**The TypeScript suite caught a real bug on the first run after this landed.**
`fields_split` is a note about how the CALLER phrased the request, and
`asFields` normalizes `"day,score"` and `["day","score"]` to the same list — so
without that distinction in the key, a caller who sent a proper list was told
its list had been split from a string. Python had the identical hole and no
test that happened to make both calls; it would have shipped. Both keys carry
it now, and both suites pin it.

Nine mutants cover the cache across the two languages, and all nine are killed.
`tools/mutate.py` itself was hard-coded to `.venv/bin/python`, which on at least
one machine is a dead symlink — so the tool that checks whether the tests have
teeth died before running one. `OURA_PYTHON` overrides it.

**A fourth tool, `oura_today`, and it computes nothing.** «How did I sleep?»
is the most common question there is, and answering it well needs last night's
sleep, today's readiness, and enough of the days before them to know whether
either is unusual. Through `oura_query` that was four round trips and four
chances to stop early. This is one call.

It spends the **three tools** figure, which was the one differentiator in this
field with an editorial stance behind it, and that was a deliberate decision
rather than a drift. What it does NOT spend is the stance itself. The competing
Go server returns a delta against a 7-day average; this returns the seven days
RAW. A delta would have made three published statements false at once — the
module docstring, `llms.txt`, and the long description going into the
directory submission — all of which say that an average computed inside the
server arrives as a number without its method. Across nine years of real data,
three out of four changes between consecutive measurements fall inside the
metric's own normal swing, so a percentage without that context manufactures a
signal rather than reporting one.

Every response carries `computed`, saying out loud that no average, delta or
trend was calculated, because a caller has to be able to tell a composition
from an analysis without reading the source. `days` is 1 to 30 and an
out-of-range value is REFUSED, not clamped: clamping answers a question nobody
asked and the answer looks identical to one to the question that was asked.
One collection failing does not lose the other — a 403 on readiness is no
reason to withhold the sleep that arrived — and `empty`, `truncated`,
`synthetic`, `cached` and the rest are carried through rather than summarised,
because a wrapper that drops them lies by omission.

**The tool count was hardcoded in nine places, and one of them was a test
asserting the old number.** `test_no_document_promises_four_tools` was correct
for a year and then defended a number that had stopped being true; it would
have passed while every document said three. It is now
`test_no_document_names_the_wrong_tool_count`, it derives the count from the
server, it checks both languages, and it exempts only CHANGELOG.md and
ROADMAP.md — which record what was true at the time on purpose. The same
treatment went to the `.mcpb` manifest guard, the read-only guard, and the
stdio smoke test, all of which compared against a literal `3`.

The description-parity guard now runs per tool instead of per file. It read
the whole of `server.ts` into one map, which worked only while `oura_query`
was the only tool with parameters and would have silently merged two schemas
the moment a second one shared a name.

**The README in Simplified Chinese, Korean and Spanish**, with a language line
at the top of each. This is a hypothesis being tested, not a feature:
`YuzeHao2023/MCP-oura` has 115 stars against the 38 of the project it is a
straight copy of, and the only visible difference is that it ships its README
in three languages. A second project moved on a Russian one. It costs no code
and falsifies itself in a month — if the stars do not move, the hypothesis is
dead and it cost a document. Each translation says plainly that it is
machine-assisted and asks for corrections.

Translating the README meant reading it closely, which found **two sentences in
it that were false**, both in the places a stranger reads first:

- **«There is no cache.»** In the privacy section — the section `SUBMISSION.md`
  names as this project's privacy policy. True this morning and false by the
  afternoon. It now states the actual guarantee, which is stronger and more
  useful than the old absolute: nothing is written to disk, closed days are
  held in memory only, and `--forget` clears them.
- **«The code, its comments and the internal documents are in Spanish, and so
  are the tool parameters.»** None of that had been true since 0.3.0 for the
  parameters, or since earlier today for the rest. A reviewer would have read
  it and then looked at an English repository.

`SUBMISSION.md` now describes the cache too. A directory reviewer who later
sees a `cached` key in a response should have met it in the submission first.

README.md's language links are absolute rather than relative, because README.md
ships to PyPI and PyPI does not rewrite relative markdown links.

**A container image, on `ghcr.io`.** For people who would rather not have a
Python on their machine at all — the one thing `Rajskij/oura-mcp` had that this
did not. `docker run -i --rm -e OURA_SANDBOX=1 ghcr.io/proscar87/oura-mcp` runs
on sample data with no account.

The check that proves it is `tools/smoke_stdio.py`, pointed at the container
through the new `OURA_SMOKE_CMD`. The first version of that job was a
`printf | docker run` pipeline, and it passed on one commit and failed on the
next with nothing between them that could touch it: closing the pipe after the
last line races the server's answer to it, so `tools/list` sometimes never came
back. A flaky guard is worse than none, because the failure reads as a real
one and the pass reads as proof. The script does not race — it writes a request
and READS the reply before sending the next, which is what a client does — and
it already checks more than the pipeline did. Writing the handshake a second
time in shell was the mistake; there was a tested driver for it already.

`-i` is load-bearing and the README says so: an MCP server speaks over stdin
and stdout, not over a port, so without it the container has no stdin and the
handshake never arrives. From the client that is indistinguishable from a
server that does not exist. CI therefore builds the image AND starts it on
every push, asserting the three tools come back by name and that nothing but
JSON-RPC reaches stdout; the publish job repeats that against the exact bytes
before pushing, and refuses to push an image that cannot answer. `docker build`
returning 0 says the layers assembled, nothing more.

The image runs as a non-root user and OAuth2 is deliberately not containerized:
authorizing opens a browser and listens on a loopback port, and neither
survives a container boundary without more flags than it is worth. Authorize on
the host and mount the credentials read-only.

Also documented `cached` in the README and `llms.txt`, and removed a line in
the README claiming parameter names are in Spanish. They stopped being Spanish
in 0.3.0.

## 0.3.4 — 7 September 2026

**The `.mcpb` described its own parameters in Spanish, and the three tests
written to catch exactly that all passed.** `tools/list` from the bundle had
been answering with «AAAA-MM-DD, o ISO 8601 con hora» as the description of
`start` and `end` since the TypeScript port landed. Parameter descriptions are
the only text a model reads before deciding how to call a tool, and the bundle
is the install path the README leads with.

Worse than the language: `ts/src/authorize.ts` returned the completed OAuth
result under a key named `alcances_concedidos` where Python returns
`granted_scopes`. That is API surface, not prose — the two halves answered the
same call with different field names, and only the Python one matched the
documentation. TypeScript now returns `granted_scopes`. Anyone reading that key
out of the bundle's authorize result has to rename it.

Comparing the two implementations also turned up two divergences that were not
Spanish at all. TypeScript's `fields` description had dropped the word
`heartrate`, and its `format` description had lost the entire reason to prefer
CSV — the ~37,000 records of a month whose four keys repeat 37,000 times — so
the half that ships in the bundle could state the advice but not justify it.
Both now match Python word for word.

**Why the guards missed it, which is the part worth keeping.** All three were
word lists. `test_no_parameter_description_is_in_spanish` scans the right file
with a regex that does match `.describe(...)`, and not one of its eight
markers appears in that string. `test_no_error_message_is_in_spanish` listed
four Python modules and three of TypeScript's four; the missing one held the
Spanish. And `test_no_dict_literal_returns_a_spanish_key` reads only Python and
compares keys for equality against a list that does contain «alcances», which
`alcances_concedidos` is not equal to. On top of that, every extractor here
matched *quoted* keys, and TypeScript object literals do not quote theirs, so
every object TypeScript returns was invisible to every guard in the file.

A word list only ever knows the vocabulary of the bug that prompted it. Two new
tests compare the implementations instead: one asserts every `oura_query`
parameter is described identically in both, the other that the OAuth result
carries the same keys in both. Neither needs a vocabulary or a file list, so
neither can go stale against words nobody predicted. The old lists stay as a
cheap net, with the missing file and markers added.

The rest of the pre-0.3.0 translation is finished in the same release: nine
comment and docstring blocks in the sources, 39 test names, 18 test docstrings,
and the fixture values a failing assertion prints. Storage keys are deliberately
untouched — `credenciales`, `credenciales.json` and `expira_en` — because
renaming them orphans the credentials of anyone who authorized before the
translation, which `test_the_keychain_account_name_is_not_renamed` already says
out loud.

One guard was written wrong on the first try and CI caught it, which is the
system working. Reading `Field(description=...)` only at the top level of an
annotation saw all seven parameters on 3.13 and three on 3.10, where
`get_type_hints` still re-wrapped anything defaulting to `None` as
`Optional[Annotated[...]]`. It recurses now, and a second test pins the 3.10
shape by hand.

## 0.3.3 — 17 August 2026

**The lone carriage return was only half fixed, and CI had been red for six
runs saying so.** 0.3.2 pinned it in TypeScript and reported it pinned on both
sides. Python's half was still the stdlib's `csv.writer`, which quotes a field
containing any character of its `lineterminator` — `"\n"` here, so a bare `\r`
is not in it. CPython 3.11 began quoting `\r` regardless
(python/cpython#128064); 3.10 did not, and `requires-python` is `>=3.10`. The
test read the CSV back with the same stdlib that wrote it, so it passed on the
developer's 3.13 and failed only on the 3.10 job — green locally, red in CI,
every push since 11 August.

`to_csv` now states the rule itself — quote on `"`, `,`, `\n`, `\r`, double the
quotes — which is `escapeCell` in `ts/src/client.ts` character for character,
and depends on no interpreter version. A second test pins the exact bytes
rather than round-tripping them, so the next divergence fails on every Python
or none.

**The differential suite had never run in CI, and neither had TypeScript's 108
tests.** `test_parity.py` skips itself without Node and a compiled `ts/dist`,
and no workflow installed either — so the `16 skipped` that every job reported
on every push was the entire suite, silent since it was written. It is the
comparison the file itself calls the highest-yield technique here: it found the
carriage return above, `rate_limited` missing on one side, milliseconds printed
as seconds, a version constant two releases stale. It now runs on both
interpreters on purpose, because the divergence it last caught existed only on
3.10. The TypeScript half had no CI at all — 108 tests, never executed, in the
implementation that ships as the `.mcpb` the README recommends first.

**And the version was wrong in two more places, both of them unpinned.** The
number lives in ten declarations; the coherence test pinned six. Of the four it
did not, `ts/package-lock.json` said **0.3.0** — two releases behind, and it is
what `npm ci` installs — and `oura_mcp.__version__` said **0.1.0**, retired
three releases earlier. Nothing caught either one because nothing read them:
`__version__` is the conventional way to ask a Python package what it is, and no
test or line of code ever did. Both are read now rather than typed —
`importlib.metadata` and `package.json`, the same fix the handshake got in 0.3.1
and `VERSION` got in 0.3.2 — and the four unpinned declarations are pinned, so
the drift that hid here twice has nowhere left to hide.

## 0.3.2 — 12 August 2026

Then a sixteen-round audit, a wave of parallel agents, and one piece of field
intelligence:

**Oura runs two portals now.** Applications registered on the newer
`developer.ouraring.com` are rejected by the legacy token endpoint on **every**
refresh — so such a registration worked exactly once, until the first access
token expired, and then failed forever. The exchange tries the legacy endpoint
and falls back to the new one, keeping the legacy error message when both
reject, because a 400 is also what a mistyped client ID produces.

**Two concurrent queries spent the single-use refresh token twice**, and one of
them failed with «Refresh token already used» — a message nobody can act on, on
a query that had nothing wrong with it. One refresh at a time now.

**Two process crashes**, both in TypeScript, both from something nobody was
listening to: a callback with a wrong `state` (which any web page can send), and
a machine without `xdg-open`. The bundle build now runs under
`--unhandled-rejections=strict`.

**Impossible dates answered confidently.** `2026-02-29` — not a leap year —
rolled over to March 1st and came back «Oura has no records in that range».
`2026-13-01` became December. Both refuse now, before the network.

**`latest=true` silently discarded the dates**, answering «my most recent heart
rate on July 3rd» with the most recent sample ever.

**A 403 named only one of its two documented causes.** Oura's spec says it
usually means an expired subscription — so telling that person to grant a scope
sent them to re-approve a permission they already held.

Plus: heart rate for a single day returned nothing and blamed Oura; a lone
carriage return shifted every CSV column after it; a recovered rate limit left
no trace; four divergences between the two implementations, including a
handshake reporting a version two releases stale.

The drift check now reads Oura's official OpenAPI spec, so a NEW collection is
detected instead of waiting for someone to read release notes. `tools/mutate.py`
breaks each guarantee on purpose and reports which ones no test would notice.
246 Python tests, 108 TypeScript.

Found by a 20-hour audit, and all of one family: a response that looks right and
is not.

**«What was my heart rate on January 1st» returned nothing.** `heartrate` and
`ring_battery_level` take `start_datetime`/`end_datetime`, and a bare date went
through untouched — `start_datetime=2026-01-01&end_datetime=2026-01-01`, an
interval of no duration. Oura returned zero and the empty-reason blamed Oura for
a window this client had emptied itself. A bare date now means the whole day.

**A rate limit that recovered left no trace.** Oura sends no rate-limit headers
on successful responses, so a 429 is the only signal a client ever gets that it
is near the ceiling — and a successful retry threw that signal away. Responses
now carry `rate_limited`.

**`fields="day,score"` was answered with a validator dump** and a link to
pydantic's website, on what is almost certainly the most common mistake anyone
will make here. Both forms are accepted now; `fields_split` says when the string
was split.

**`discarded_out_of_range` was a bare integer that read as data loss.** It fires
on nearly every dated query — the two-day margin is always requested and always
trimmed — so it reported the safety margin working. It is a sentence now.

**`oura://collections` is a new resource:** the catalog, static, no network or
credentials. The likeliest mistake here is inventing a collection name, and a
resource puts the list in front of the model before the mistake.

Four Spanish user-facing error messages survived the translation and are gone.
The keychain account name stays `credenciales` deliberately — it is a storage
key, and renaming it would silently orphan the credentials of anyone who
authorized earlier.

## 0.3.1 — 10 August 2026

`continue_from` pointed at something you could not use. It carried Oura's
`next_token`, and **no tool parameter accepts a token back** — deliberately,
because a cursor parameter hands pagination to the model, which is the failure
this package exists to prevent. So a truncated response told the model to
"continue from `continue_from`" and gave it nowhere to put the value.

It is now the last day actually reached, which works with the `start` parameter
that already exists. When the records carry no day at all, the key is omitted
rather than sent as null — `continue_from: null` reads as "resuming is possible
and the value is missing", which is worse than not offering it.

Eight retired Spanish key names were still documented in the README and
`llms.txt`: `campos_ignorados`, `ciclo_de_paginacion`,
`descartados_fuera_de_rango`, `respuesta_grande`. Worse than a dead CLI flag,
which fails loudly — a key that never arrives just looks like the condition never
happened. Tests now check the documented keys against the ones the code emits,
and check the two implementations against each other.

## 0.3.0 — unreleased

Everything in English: docs, comments, and the tool parameters. The parameter
rename is a **breaking change** against 0.2.0 — `dia` → `day`, `inicio` →
`start`, `fin` → `end`, `campos` → `fields`, `ultimo` → `latest`, `formato` →
`format`, `collection` → `collection`. They now match Oura's own API names,
which is one less translation layer for anyone reading both.

The CLI flags were renamed with them: `--autorizar` → `--authorize`,
`--revisar` → `--check`, `--olvidar` → `--forget`. The README, `llms.txt` and
`AGENTS.md` went on citing the old ones for a while — twelve commands that
answered `I don't know --revisar`. A test now checks every flag quoted in the
documentation against the list the CLI actually accepts.

TypeScript port, with parity verified against the Python implementation on the
real API: the same 1,231 records in the same order for the two-page `heartrate`
case that justifies the project. Node ships with Claude Desktop, which removes
the binary, the code signing and the per-platform CI that the `.mcpb` would
otherwise need.

## 0.2.0 — 9 August 2026

0.1.x paginated. This one fixes three more ways Oura under-delivers without
saying so, and opens the door Oura closed in December 2025.

Everything below was measured against the real API, not assumed.

### The date range was wrong

Asking for a single day returned **zero records** in `daily_activity`, `sleep`
and `workout`. No error, no `truncated`, and `paginas: 1` asserting the page was
complete. Two failures that stack:

- **`end_date` is inconsistent across collections.** Three exclude the last day;
  seven include it.
- **`workout` filters by UTC date but reports `day` in local time.** At `-06:00`,
  asking for July 16–18 returned the 15th and 16th.

The range is now inclusive on both ends, always: two extra days are requested on
each side and trimmed. That's correct whichever way a collection behaves, and
stays correct when Oura changes it.

New `day` parameter for the most common query.

### Two Oura parameters we weren't using, and their traps

- **`fields`** — trims on Oura's side, so less comes down.
- **`latest`** — the most recent record without pulling the whole window.

Both fail silently when misused: `fields=made_up` returns the complete record
without projecting, and `latest=true` on a collection that doesn't support it
returns the entire collection. So `latest` is rejected here for the 17 that
don't honor it, and fields that were never applied are reported under
`ignored_fields`.

### Sandbox mode

`OURA_SANDBOX=1` uses Oura's official mirror routes, which serve synthetic data
without credentials. 18 of the 19 collections work — not `personal_info`, the
one returning email, age, weight and height.

### OAuth2

Oura stopped issuing Personal Access Tokens in December 2025. `oura-mcp
--autorizar` runs the full flow, with `--manual` for headless machines and
`--olvidar` to erase credentials.

Oura's refresh token is single-use: it's saved before being returned, atomically,
and if two processes refresh at once the loser re-reads what's on disk instead of
declaring the session lost. The callback's `state` is verified with a
constant-time comparison.

Tokens live in `~/.config/oura-mcp/credenciales.json` with mode 600 — or in the
system keychain if you have `keyring`, which is not a dependency. Personal tokens
still work and win when present.

### Volume and warnings

- **`format="csv"`** — savings vary by collection: 55% on `heartrate`, 10% on
  `daily_sleep`. The header comes from the union of all keys, not the first
  record.
- **`truncated` now carries `continue_from`** so you can resume instead of
  retrying blind.
- **429 with bounded retry**, honoring `Retry-After` in both its forms. Oura
  sends no rate-limit headers, so reacting well is all that's left.

### Errors you can read

Oura's `detail` arrives in two shapes and neither reads well raw. Now it's
translated: `start_date: Input should be a valid datetime or date (received:
'ayer')` instead of JSON cut off mid-word. And an inverted range is caught here,
citing the dates you wrote rather than the ones we sent with the margin.

### Everything else

- All three tools declare `title` and `readOnlyHint`. A test reads the source to
  keep that true.
- The token is wrapped in a type that won't print in a stack trace.
- Claude Code plugin, `smithery.yaml`, `glama.json`, `llms.txt`.
- `tools/check_drift.py` and a weekly job checking that all 19
  collections still exist, without credentials.
- 124 tests, none of which touch the network.

## 0.1.1 — 9 August 2026

Ownership proof for the MCP registry.

## 0.1.0 — 9 August 2026

First release. All 19 collections, three tools, complete pagination.
