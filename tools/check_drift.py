#!/usr/bin/env python3
"""Does every one of the 19 collections declared in `collections.py` still exist?

IT RUNS AGAINST OURA'S SANDBOX, WHICH ASKS FOR NO CREDENTIALS. That's why it can
live in CI without depending on anyone's token — which is this repository's rule:
a CI that needs someone's token to pass isn't a CI, it's a dependency on that
person.

WHAT IT CATCHES AND WHAT IT DOESN'T
    Yes  a collection Oura renamed, moved or retired.
    No   a NEW collection. The sandbox can't be enumerated, so discovering
         additions is still human work — today, reading the release notes.

WHY IT DOESN'T COMPARE AGAINST THE OPENAPI SPEC
That would be the right thing and it isn't possible: Oura doesn't publish its
`openapi.json` at any stable URL. Five plausible paths were tried on 2026-08-09
and all five return 404. The only public copy we found is vendored in a third
party's repository (`spxrogers/oura-toolkit`), and hanging our CI off someone
else's repo trades one dependency for a worse one.

    $ python tools/check_drift.py
"""

from __future__ import annotations

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
    print("Remember: this does NOT detect new collections.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
