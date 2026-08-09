# Changelog

## 0.3.0 — unreleased

Everything in English: docs, comments, and the tool parameters. The parameter
rename is a **breaking change** against 0.2.0 — `dia` → `day`, `inicio` →
`start`, `fin` → `end`, `campos` → `fields`, `ultimo` → `latest`, `formato` →
`format`, `coleccion` → `collection`. They now match Oura's own API names,
which is one less translation layer for anyone reading both.

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
and `workout`. No error, no `truncado`, and `paginas: 1` asserting the page was
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
`campos_ignorados`.

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
- **`truncado` now carries `continuar_desde`** so you can resume instead of
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
