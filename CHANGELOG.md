# Changelog

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
