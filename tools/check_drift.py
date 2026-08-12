#!/usr/bin/env python3
"""Does every one of the 19 collections declared in `collections.py` still exist?

IT RUNS AGAINST OURA'S SANDBOX, WHICH ASKS FOR NO CREDENTIALS. That's why it can
live in CI without depending on anyone's token — which is this repository's rule:
a CI that needs someone's token to pass isn't a CI, it's a dependency on that
person.

WHAT IT CATCHES
    A collection Oura renamed, moved or retired  — by asking the sandbox.
    A collection Oura ADDED                      — by reading the official spec.

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

os.environ["OURA_SANDBOX"] = "1"

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from oura_mcp.client import OuraError, base, fetch                    # noqa: E402
from oura_mcp.collections import COLLECTIONS, WITHOUT_SANDBOX, shape  # noqa: E402

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


def spec_collections() -> tuple[set[str], str] | None:
    """The collection names in Oura's official spec, and which spec that was.

    Returns None if anything at all goes wrong. This check is advisory and runs
    in an optional weekly job: a docs page that changed its markup must report
    "couldn't read it", never fail the run and never invent an answer.
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

    nombres = {
        p.rsplit("/", 1)[-1]
        for p in spec.get("paths", {})
        if p.startswith("/v2/usercollection/") and "{" not in p
    }
    return (nombres, ruta.rsplit("/", 1)[-1]) if nombres else None


def check_the_spec() -> int:
    """Compare `collections.py` against the official spec, in both directions."""
    resultado = spec_collections()
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
    return 1 if nuevas or idas else 0


def main() -> int:
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
    sys.exit(main())
