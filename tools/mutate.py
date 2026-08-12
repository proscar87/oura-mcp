#!/usr/bin/env python3
"""Break each core guarantee on purpose and report which ones nobody notices.

WHY THIS EXISTS. A green suite says the tests pass. It does not say the tests
would fail if the product broke, and those are different claims. Running this
found two guarantees with no teeth behind them, in a repository that already had
255 passing tests:

    ignored_fields (TypeScript)   the helper was tested, the wiring was not —
                                  deleting the line that attaches the warning to
                                  the response broke nothing at all
    Secret / node inspect         `toString` and `toJSON` were covered and
                                  `nodejs.util.inspect.custom` was not, which is
                                  the one that fires inside a stack trace — the
                                  exact way a token leaked here once

It also correctly reported a NON-finding: changing the file mode on `writeFile`
goes unnoticed because an explicit `chmod` after it makes that argument
redundant. Defense in depth looks identical to a coverage hole from the outside,
and only reading the code tells them apart. A surviving mutant is a question,
not a verdict.

    python tools/mutate.py            # both suites
    python tools/mutate.py --python   # just this one

IT RUNS THE TEST SUITES, WHICH NEVER TOUCH THE NETWORK. It edits files in place
and restores them in a `finally`; if it is killed mid-run, `git status` will show
you what to revert.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).parent.parent

# (name, file, [(before, after), …])
PYTHON = [
    ("paginate to exhaustion", "src/oura_mcp/client.py",
     [("        if not next_token:", "        if True:")]),
    ("the ±2-day margin", "src/oura_mcp/client.py",
     [('params["start_date"] = _shift_days(start, -EXTRA_DAYS)', 'params["start_date"] = start')]),
    ("trim what the margin brought in", "src/oura_mcp/client.py",
     [("    data, discarded = _trim(data, start, end, s)", "    discarded = 0")]),
    ("detect the next_token cycle", "src/oura_mcp/client.py",
     [("        if next_token in seen:", "        if False:")]),
    ("reject latest where it does not apply", "src/oura_mcp/client.py",
     [("WITH_LATEST", "WITH_DATE")]),
    ("warn about ignored fields", "src/oura_mcp/client.py",
     [("    if (ignored := _ignored_fields(fields, data)):", "    if False:")]),
    ("warn about a large response", "src/oura_mcp/client.py",
     [("    if (warning := _size_warning(data, fields)):", "    if False:")]),
    ("widen a bare date to the whole day", "src/oura_mcp/client.py",
     [('params[f"start_{key}"] = _widen_start(start)', 'params[f"start_{key}"] = start')]),
    ("mark the sample data", "src/oura_mcp/client.py",
     [("    if in_sandbox():\n", "    if False:\n")]),
    ("report a recovered 429", "src/oura_mcp/client.py",
     [("    if waits:", "    if False:")]),
    ("a 403 names the missing scope", "src/oura_mcp/client.py",
     [('            if "403" in str(e):', "            if False:")]),
    ("Secret is not printable", "src/oura_mcp/client.py",
     [('        return f"<secret, {len(self._value)} characters>"', "        return self._value")]),
    ("the new-portal token endpoint is tried on a 400", "src/oura_mcp/credentials.py",
     [('        if "(400)" not in str(legado):\n            raise', "        raise")]),
    ("a mistyped client id keeps the legacy error", "src/oura_mcp/credentials.py",
     [("            raise legado from None                    # the better sentence wins",
       "            raise")]),
    ("one refresh at a time", "src/oura_mcp/credentials.py",
     [("    with _REFRESH_LOCK:\n        return _refresh_locked(cred, client_id, client_secret)",
       "    return _refresh_locked(cred, client_id, client_secret)")]),
    ("an impossible calendar date is refused", "src/oura_mcp/client.py",
     [("        raise OuraError(\n            f\"`{date[:10]}` is not a real date",
       "        return date  # noqa\n        raise OuraError(\n            f\"`{date[:10]}` is not a real date")]),
    ("latest plus a date range is refused", "src/oura_mcp/client.py",
     [("    if latest and (start or end):", "    if False:")]),
    ("a 401 blames the credential, not the scopes", "src/oura_mcp/client.py",
     [("            if e.code == 401:", "            if False:")]),
    ("an empty response names the missing scope", "src/oura_mcp/client.py",
     [("    if missing:\n        reasons.append(missing)",
       "    if False:\n        reasons.append(missing)")]),
    ("the credentials file leaves no debris", "src/oura_mcp/credentials.py",
     [("        try:\n            os.unlink(temporal)\n        except OSError:\n            pass\n        raise",
       "        raise")]),
]

TYPESCRIPT = [
    ("paginate to exhaustion", "ts/src/client.ts", [("    if (!nextToken) break;", "    break;")]),
    ("the ±2-day margin", "ts/src/client.ts",
     [('params.set("start_date", shiftDays(start, -EXTRA_DAYS));', 'params.set("start_date", start);')]),
    ("detect the nextToken cycle", "ts/src/client.ts", [("if (seen.has(nextToken))", "if (false)")]),
    ("reject latest where it does not apply", "ts/src/client.ts",
     [("WITH_LATEST.has(collection)", "true")]),
    ("warn about ignored fields", "ts/src/client.ts", [("if (ignored.length)", "if (false)")]),
    ("mark the sample data", "ts/src/client.ts", [("  if (inSandbox()) {\n    //", "  if (false) {\n    //")]),
    ("report a recovered 429", "ts/src/client.ts", [("if (waits.length) {", "if (false) {")]),
    ("widen a bare date to the whole day", "ts/src/client.ts",
     [('params.set("start_datetime", widenStart(start));', 'params.set("start_datetime", start);')]),
    ("a 403 names the missing scope", "ts/src/client.ts",
     [('String(e.message).includes("403")', "false")]),
    ("Secret is not printable", "ts/src/client.ts",
     [("return `<secret, ${this.#valor.length} characters>`;", "return this.#valor;")]),
    ("Secret survives node's inspect", "ts/src/client.ts",
     [('[Symbol.for("nodejs.util.inspect.custom")](): string {\n    return this.toString();',
       '[Symbol.for("nodejs.util.inspect.custom")](): string {\n    return this.#valor;')]),
    ("CSV quotes what would shift a column", "ts/src/client.ts",
     [("""/[",\\n\\r]/.test(s)""", "/never-matches/.test(s)")]),
    ("an impossible calendar date is refused", "ts/src/client.ts",
     [("  if (normalizado !== m[0]) {", "  if (false) {")]),
    ("latest plus a date range is refused", "ts/src/client.ts",
     [("  if (latest && (start || end)) {", "  if (false) {")]),
    ("a 401 blames the credential, not the scopes", "ts/src/client.ts",
     [("    if (r.status === 401) {", "    if (false) {")]),
    ("an empty response names the missing scope", "ts/src/client.ts",
     [("  if (missing) reasons.push(missing);", "  if (false) reasons.push(missing);")]),
    ("warn about a large response", "ts/src/client.ts",
     [('  if (warning) out["large_response"] = warning;',
       '  if (false) out["large_response"] = warning;')]),
    ("flag uneven CSV columns", "ts/src/client.ts",
     [("    if (uneven) {", "    if (false) {")]),
    ("the sandbox turns off with 0/no/false", "ts/src/client.ts",
     [('  return v !== "" && !["0", "no", "false"].includes(v);', '  return v !== "";')]),
    ("an occupied port stops waiting instead of hanging", "ts/src/authorize.ts",
     [("      clearTimeout(timer);\n      // Only if it ever listened.", "      // Only if it ever listened.")]),
    ("a missing browser opener does not kill the process", "ts/src/authorize.ts",
     [('    child.on("error", () => { /* the URL is on stderr; that is the fallback */ });\n', "")]),
    ("a stray callback does not kill the process", "ts/src/authorize.ts",
     [("  promise.catch(() => {});", "")]),
    ("the new-portal token endpoint is tried on a 400", "ts/src/credentials.ts",
     [('    if (!(legacy instanceof OuraError) || !String(legacy.message).includes("(400)")) {\n      throw legacy;              // 401, 5xx, unreachable: not this problem\n    }', "    throw legacy;")]),
    ("a mistyped client id keeps the legacy error", "ts/src/credentials.ts",
     [("      throw legacy;              // the better sentence wins", "      throw e2;")]),
    ("one refresh at a time", "ts/src/credentials.ts",
     [("  if (inFlight) return inFlight;", "")]),
    ("the credentials file leaves no debris", "ts/src/credentials.ts",
     [("await rm(tmp, { force: true });", "")]),
]

PY_CMD = [".venv/bin/python", "-m", "pytest", "-q", "-p", "no:cacheprovider"]
TS_CMD = ["npx", "vitest", "run"]


def run(mutants, cmd, cwd) -> int:
    survived = 0
    for name, rel, edits in mutants:
        p = ROOT / rel
        original = p.read_text(encoding="utf-8")
        text, applicable = original, True
        for before, after in edits:
            if before not in text:
                print(f"  ?      {name}  (pattern not found — did the code move?)")
                applicable = False
                break
            text = text.replace(before, after, 1)
        if not applicable:
            survived += 1
            continue
        p.write_text(text, encoding="utf-8")
        try:
            r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=300)
            caught = "failed" in (r.stdout + r.stderr).lower()
        finally:
            p.write_text(original, encoding="utf-8")
        print(f"  {'ok    ' if caught else 'SURVIVED'} {name}")
        survived += not caught
    return survived


def main() -> int:
    which = sys.argv[1] if len(sys.argv) > 1 else "--all"
    total = 0
    if which in ("--all", "--python"):
        print("Python")
        total += run(PYTHON, PY_CMD, ROOT)
    if which in ("--all", "--typescript"):
        print("TypeScript")
        total += run(TYPESCRIPT, TS_CMD, ROOT / "ts")
    print()
    if total:
        print(f"{total} mutant(s) survived. Read the code before adding a test: "
              f"some survive because another line already covers them.")
        return 1
    print("Every guarantee has a test with teeth behind it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
