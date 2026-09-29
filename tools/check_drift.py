#!/usr/bin/env python3
"""Does every one of the 19 collections declared in `collections.py` still exist?

IT RUNS AGAINST OURA'S SANDBOX, WHICH ASKS FOR NO CREDENTIALS. That's why it can
live in CI without depending on anyone's token — which is this repository's rule:
a CI that needs someone's token to pass isn't a CI, it's a dependency on that
person.

WHAT IT CATCHES
    A collection Oura renamed, moved or retired  — by asking the sandbox.
    A collection Oura ADDED                      — by reading the official spec.
    A scope Oura added, renamed or dropped       — by reading the spec's OAuth
                                                   block (see `compare_scopes`).

THE SECOND ONE USED TO SAY "isn't possible". This file claimed Oura publishes no
`openapi.json` at any stable URL, on the evidence that five guessed paths all
404'd — and concluded that finding new collections was human work. Five guesses
are not a search. The docs page states the answer itself:

    $ curl -s https://cloud.ouraring.com/v2/docs | grep spec-url
    <redoc spec-url="/v2/static/json/openapi-1.37.json">

It downloads without credentials. Verified 2026-08-12: 453 KB, 19
`/v2/usercollection/*` list routes, matching `collections.py` exactly.

The version in that filename moves, which is why the path is READ from the docs
page rather than pinned. That indirection is the whole trick, and it is why the
original guesses failed: there is no stable URL, and there is a stable way to
find the current one.

    $ python tools/check_drift.py
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from oura_mcp.client import OuraError, base, fetch                    # noqa: E402
from oura_mcp.collections import COLLECTIONS, SCOPE_OF, WITHOUT_SANDBOX, shape  # noqa: E402
from oura_mcp.credentials import SCOPES, normalize_scopes                   # noqa: E402

# The sandbox serves 18 of the 19; the missing one is declared in
# `collections.py`, which is also where the client reads it from. Its absence
# isn't drift, so it's expected explicitly rather than tolerated in silence.

WINDOW = ("2026-01-01", "2026-01-05")
WINDOW_TIME = ("2026-01-01T00:00:00", "2026-01-02T00:00:00")


def check_one(name: str) -> tuple[bool, str]:
    s = shape(name)
    args = WINDOW if s == "date_range" else WINDOW_TIME if s == "datetime_range" else ()

    if name in WITHOUT_SANDBOX:
        # ASK OURA DIRECTLY, bypassing the client's guard. Using `fetch()` here
        # would mean this check verified our own error message instead of the
        # API — and the day Oura adds this collection to the sandbox, nobody
        # would notice. A check that checks itself checks nothing.
        from oura_mcp.client import _request, _token
        try:
            _request(f"{base()}/{name}", _token())
        except OuraError as e:
            if "404" in str(e):
                return True, "absent from the sandbox, as expected"
            return False, str(e)[:90]
        return False, "it IS in the sandbox now: update WITHOUT_SANDBOX"

    try:
        r = fetch(name, *args)
    except OuraError as e:
        return False, str(e)[:90]
    return True, f"responds, n={r['n']}"


DOCS_URL = "https://cloud.ouraring.com/v2/docs"


def fetch_spec() -> tuple[dict, str] | None:
    """Oura's official spec and its filename, or None if anything goes wrong.

    Advisory, in an optional weekly job: a docs page that changed its markup
    must report "couldn't read it", never fail the run and never invent an
    answer.
    """
    import re
    import urllib.request

    try:
        with urllib.request.urlopen(DOCS_URL, timeout=30) as r:
            pagina = r.read().decode("utf-8", "replace")
        m = re.search(r'spec-url="([^"]+)"', pagina)
        if not m:
            return None
        ruta = m.group(1)
        url = ruta if ruta.startswith("http") else f"https://cloud.ouraring.com{ruta}"
        with urllib.request.urlopen(url, timeout=60) as r:
            spec = json.load(r)
    except Exception:
        return None
    return spec, ruta.rsplit("/", 1)[-1]


def spec_collections(fetched: tuple[dict, str] | None = None) -> tuple[set[str], str] | None:
    """The collection names in Oura's official spec, and which spec that was."""
    fetched = fetched or fetch_spec()
    if fetched is None:
        return None
    spec, version = fetched
    nombres = {
        p.rsplit("/", 1)[-1]
        for p in spec.get("paths", {})
        if p.startswith("/v2/usercollection/") and "{" not in p
    }
    return (nombres, version) if nombres else None


# Offered by Oura and deliberately not requested, each with the reason. A scope
# lands here only by decision; one that appears in the spec and is in neither
# list fails the run until someone makes that decision.
KNOWN_UNREQUESTED = {
    "heart_health": "added in spec 1.40; no collection is documented as needing "
                    "it. Requested the day one is — `compare_scopes` will say so "
                    "if the spec starts declaring it per collection.",
}


def compare_scopes(spec: dict) -> tuple[list[str], bool | None]:
    """The spec's OAuth scopes against `SCOPES`, `SCOPE_OF` and the prefix rule.

    Returns printable lines and whether anything drifted; None for «drifted»
    when the spec carries no OAuth block to compare, which is unreadable, not
    empty.
    """
    offered: set[str] = set()
    for scheme in (spec.get("components", {}).get("securitySchemes") or {}).values():
        for flow in (scheme.get("flows") or {}).values():
            offered |= set(flow.get("scopes") or {})
    if not offered:
        return ["  ??   the spec has no OAuth scopes block to compare"], None

    lines, bad = [], False
    requested = set(SCOPES)
    gone = sorted(requested - offered)
    new = sorted(offered - requested - set(KNOWN_UNREQUESTED))
    if gone:
        bad = True
        lines.append(f"  GONE   requested but no longer offered: {', '.join(gone)} — "
                     f"renamed? (spo2Daily became spo2 in 1.40). Fix SCOPES in "
                     f"credentials.py and SCOPE_OF in collections.py, both languages.")
    if new:
        bad = True
        lines.append(f"  NEW    offered and not requested: {', '.join(new)} — request "
                     f"it, or add it to KNOWN_UNREQUESTED with the reason.")
    for name in sorted(offered & set(KNOWN_UNREQUESTED)):
        lines.append(f"  ok     {name} offered, not requested on purpose: "
                     f"{KNOWN_UNREQUESTED[name]}")
    if not gone and not new:
        lines.append(f"  ok     the spec offers the {len(requested)} scopes requested")

    # The prefix Oura began granting in September 2026, which the spec does not
    # mention: every offered scope must still read as itself once prefixed.
    broken = [s for s in sorted(offered) if normalize_scopes([f"extapi:{s}"]) != (s,)]
    if broken:
        bad = True
        lines.append(f"  BAD    normalize_scopes no longer reads extapi:{broken[0]} as {broken[0]}")
    else:
        lines.append("  ok     every offered scope reads as itself when granted as extapi:…")

    # Per collection. Oura declares none today — which is why `heart_health` and
    # `stress` are open questions in the ROADMAP — and the day it does, this is
    # where they get answered.
    declared = {}
    for path, ops in (spec.get("paths") or {}).items():
        if not path.startswith("/v2/usercollection/") or "{" in path:
            continue
        name = path.rsplit("/", 1)[-1]
        needs = {s for op in ops.values() if isinstance(op, dict)
                 for req in op.get("security") or [] for group in req.values() for s in group}
        if needs:
            declared[name] = needs
    if not declared:
        lines.append("  --     the spec declares no per-collection scopes, so SCOPE_OF "
                     "is unchecked against it")
    for name, needs in sorted(declared.items()):
        ours = SCOPE_OF.get(name)
        if ours not in needs:
            bad = True
            lines.append(f"  BAD    {name} needs {', '.join(sorted(needs))} per the spec; "
                         f"SCOPE_OF says {ours}")
    if declared and not any(l.startswith("  BAD    ") and "needs" in l for l in lines):
        lines.append(f"  ok     SCOPE_OF matches the {len(declared)} collections the spec "
                     f"declares a scope for")
    return lines, bad


FINGERPRINT = os.path.join(os.path.dirname(__file__), "spec_fingerprint.json")


def fingerprint(spec: dict) -> dict:
    """Everything in the spec a client can depend on, and nothing that is prose.

    KEPT IN THE REPOSITORY BECAUSE OURA IS NOT. Superseded specs are deleted —
    1.37 and 1.40 both answer 404 — so the only way to know what a new version
    changed is a copy of what the last one said. Descriptions are left out on
    purpose: they change often and change nothing.
    """
    paths = {}
    for path, ops in (spec.get("paths") or {}).items():
        for method, op in ops.items():
            if isinstance(op, dict) and method in ("get", "post", "put", "patch", "delete"):
                paths[f"{method.upper()} {path}"] = sorted(
                    p.get("name", "") for p in op.get("parameters") or [] if isinstance(p, dict))
    schemas = {}
    for name, sch in ((spec.get("components") or {}).get("schemas") or {}).items():
        entry = {}
        if sch.get("properties"):
            entry["properties"] = sorted(sch["properties"])
        if sch.get("enum"):
            entry["enum"] = sorted(str(v) for v in sch["enum"])
        schemas[name] = entry
    scopes = set()
    for scheme in ((spec.get("components") or {}).get("securitySchemes") or {}).values():
        for flow in (scheme.get("flows") or {}).values():
            scopes |= set(flow.get("scopes") or {})
    return {"paths": dict(sorted(paths.items())), "schemas": dict(sorted(schemas.items())),
            "scopes": sorted(scopes)}


def fingerprint_changes(old: dict, new: dict) -> list[str]:
    """What moved between two fingerprints, one line each. Empty when nothing."""
    out = []
    for key, label in (("paths", "route"), ("schemas", "schema")):
        a, b = old.get(key, {}), new.get(key, {})
        for k in sorted(set(b) - set(a)):
            out.append(f"  +{label}  {k}")
        for k in sorted(set(a) - set(b)):
            out.append(f"  -{label}  {k}")
        for k in sorted(set(a) & set(b)):
            if a[k] == b[k]:
                continue
            if key == "paths":
                out.append(f"  ~route   {k}: parameters {a[k]} -> {b[k]}")
                continue
            for part in ("properties", "enum"):
                x, y = set(a[k].get(part, [])), set(b[k].get(part, []))
                if x != y:
                    more = f" +{sorted(y - x)}" if y - x else ""
                    less = f" -{sorted(x - y)}" if x - y else ""
                    out.append(f"  ~schema  {k}.{part}:{more}{less}")
    x, y = set(old.get("scopes", [])), set(new.get("scopes", []))
    if x != y:
        out.append(f"  ~scopes  +{sorted(y - x)} -{sorted(x - y)}")
    return out


def check_the_fingerprint(spec: dict, version: str) -> int:
    new = fingerprint(spec)
    try:
        with open(FINGERPRINT, encoding="utf-8") as f:
            old = json.load(f)
    except FileNotFoundError:
        old = None
    print(f"\nfingerprint (routes, parameters, fields, enums, scopes)")
    if old is None:
        print("  ??   no committed fingerprint; run with --update-fingerprint")
        return 1
    changes = fingerprint_changes(old, new)
    if not changes:
        print(f"  ok     {version} changes nothing a client depends on since {old['version']}")
        return 0
    print(f"  CHANGED since {old['version']} — {version}:")
    for line in changes:
        print(line)
    print("  Read each against the code, then: python tools/check_drift.py --update-fingerprint")
    return 1


def write_fingerprint() -> int:
    fetched = fetch_spec()
    if fetched is None:
        print("could not read the spec")
        return 1
    spec, version = fetched
    with open(FINGERPRINT, "w", encoding="utf-8") as f:
        json.dump({"version": version, **fingerprint(spec)}, f, indent=1, sort_keys=False)
        f.write("\n")
    print(f"fingerprint written from {version}")
    return 0


def check_the_spec() -> int:
    """Compare `collections.py` and the requested scopes against the spec."""
    fetched = fetch_spec()
    resultado = spec_collections(fetched)
    if resultado is None:
        print("  ??   the official spec could not be read — checked the sandbox only")
        print("       (advisory: a docs page that changed its markup is not a failure)")
        return 0

    nombres, version = resultado
    nuevas = sorted(nombres - set(COLLECTIONS))
    idas = sorted(set(COLLECTIONS) - nombres)
    print(f"  against {version}: {len(nombres)} collections in the spec")
    if nuevas:
        print(f"  NEW    Oura added: {', '.join(nuevas)}")
        print("         Add them to collections.py — with the right shape and scope.")
    if idas:
        print(f"  GONE   in collections.py and not in the spec: {', '.join(idas)}")
    if not nuevas and not idas:
        print("  ok     the spec and collections.py name exactly the same 19")

    print("\nscopes")
    lines, bad = compare_scopes(fetched[0])
    for line in lines:
        print(line)
    moved = check_the_fingerprint(*fetched)
    return 1 if nuevas or idas or bad or moved else 0


def main() -> int:
    # Here, not at import: the tests import this module, and a sandbox switched
    # on for the whole test run would quietly change what every later test sees.
    os.environ["OURA_SANDBOX"] = "1"
    print(f"collection drift against {base()}\n")
    failures = []
    for name in COLLECTIONS:
        ok, detail = check_one(name)
        print(f"  {'ok ' if ok else 'BAD'}  {name:<26} {detail}")
        if not ok:
            failures.append(name)
    print()
    if failures:
        print(f"{len(failures)} collection(s) drifted: {', '.join(failures)}")
        print("Check collections.py against Oura's release notes.")
        return 1
    print(f"All {len(COLLECTIONS)} collections are still where collections.py says.")
    print()
    print("official spec")
    return check_the_spec()


if __name__ == "__main__":
    if "--update-fingerprint" in sys.argv[1:]:
        sys.exit(write_fingerprint())
    sys.exit(main())
