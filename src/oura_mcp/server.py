"""MCP server: three tools over Oura's 19 collections.

THREE, NOT NINETEEN. A server with one tool per collection forces the model to
choose among 19 similar names before knowing what any of them contain, and each
one has to be documented separately. Here the collection is a parameter and the
catalog is consulted when needed, not memorised.

THERE ARE NO ANALYSIS TOOLS. No correlations, no anomaly detection, no period
comparison — which is where other servers place their value.

The reason: an average computed in here reaches the model as a number without
its method. Across nine years of real data, **three out of four changes between
two consecutive measurements fall within the metric's own normal oscillation**. A
server that hands over "your HRV is up 12%" without saying how much that metric
swings on its own isn't informing: it's manufacturing a signal. Here the data is
handed over; the analysis belongs where the method can be cited.
"""

from __future__ import annotations

import os
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from .client import OuraError, fetch
from .collections import COLLECTIONS, WITH_DATE, describe, shape

# ALL THREE ARE READ-ONLY, and that isn't a promise: there isn't a single write
# in the whole package — no POST, no PUT, no DELETE. Declaring it stops the
# client asking for confirmation on every call, and Claude's connectors
# directory requires it (`title` and `readOnlyHint` on every tool).
#
# `open_world_hint` is True because the data comes from an external service: the
# same call twice can return something different if the ring synced in between.
# Saying otherwise would invite someone to memoize the response.
_SOLO_LECTURA = dict(read_only_hint=True, destructive_hint=False,
                     idempotent_hint=True, open_world_hint=True)

def _version() -> str:
    """The installed package's version, not a hand-written copy.

    It was hand-written and stayed at 0.1.0 while `pyproject.toml` moved to
    0.2.0. The stdio smoke test caught it, not the function tests: the number an
    MCP client sees comes from the handshake's `serverInfo`, which no function
    test looks at. A server that lies about its version makes it impossible to
    answer "do you have the one with the fix?".
    """
    try:
        from importlib.metadata import version
        return version("mcp-oura")
    except Exception:
        return "unknown"


server = MCPServer(
    name="oura",
    version=_version(),
    # WHAT A MODEL CANNOT GUESS. Verified by simulating the questions a user
    # actually asks ("how did I sleep last night?", "am I recovered?", "how was
    # my heart rate during yesterday's workout?") and seeing what they were
    # missing to answer without inventing. These instructions travel in every
    # session, so only what changes an answer goes in.
    instructions=(
        "Raw data from the Oura ring, via its v2 API.\n\n"
        "FOUR THINGS THAT CHANGE THE ANSWER:\n\n"
        "1. `n: 0` does NOT mean the person didn't sleep, didn't move or didn't "
        "recover. It means Oura has no records in that range, and the most common "
        "cause is that the ring hasn't synced yet — the current day is almost "
        "always missing. When that happens the response carries `empty` with what "
        "is known. Read it before concluding anything, and say there is no data, "
        "not that it didn't happen.\n\n"
        "2. If `truncated` appears, data is MISSING: `continue_from` is the last "
        "day reached, and you ask again with `start` set to the day after. If "
        "`pagination_cycle` appears, Oura repeated itself and what you have may "
        "be incomplete. Neither one gets ignored.\n\n"
        "3. The range is inclusive on both ends, and `day` is the shorthand for "
        "a single one. To join a workout with the heart rate during it: request "
        "`workout`, take `start_datetime` and `end_datetime` from the one you "
        "care about, and use them verbatim as `start` and `end` of `heartrate`.\n\n"
        "4. Some collections are enormous: 30 days of `daily_activity` is "
        "250,000 characters, and 92% of it is a single field. If the response "
        "carries `large_response`, ask again with `fields` limited to what you "
        "need.\n\n"
        "This server deliberately computes no averages and no trends: it hands "
        "over the data so the analysis happens where the method can be cited."
    ),
)


@server.tool(title="Oura collection catalog",
               annotations=ToolAnnotations(title="Oura collection catalog",
                                           **_SOLO_LECTURA))
def oura_collections() -> dict:
    """The 19 Oura collections, what each one carries and which parameters it takes.

    Use it before `oura_query` if you are unsure of the exact name.
    """
    return {n: {"shape": f, "que_trae": d} for n, (f, d) in COLLECTIONS.items()}


@server.tool(title="Query an Oura collection",
               annotations=ToolAnnotations(title="Query an Oura collection",
                                           **_SOLO_LECTURA))
def oura_query(
    collection: Annotated[str, Field(description="Nombre exacto. Ver `oura_collections`.")],
    start: Annotated[str | None, Field(description="YYYY-MM-DD, or ISO 8601 with time")] = None,
    end: Annotated[str | None, Field(description="YYYY-MM-DD, or ISO 8601 with time")] = None,
    day: Annotated[str | None, Field(
        description="Shorthand for a single day: equivalent to start=end=day.")] = None,
    fields: Annotated[list[str] | str | None, Field(
        description="Only these fields. Oura trims on its side, so less comes "
                    "down: use it on long heartrate ranges. `day` and `id` "
                    "always come back.")] = None,
    latest: Annotated[bool, Field(
        description="Only the most recent record. heartrate and "
                    "ring_battery_level only; it needs no range.")] = False,
    format: Annotated[str, Field(
        description="`json` (default) or `csv`. CSV for large volumes: "
                    "a month of heartrate is ~37,000 records and in JSON the "
                    "keys repeat 37,000 times.")] = "json",
) -> dict:
    """Fetches a COMPLETE Oura collection over the requested range.

    Follows pagination to the end: Oura returns `next_token` and whoever doesn't
    chase it receives the first page with nothing saying so. One local day of
    `heartrate` is 1,231 samples across 2 pages; a month, ~37,000.

    The range is INCLUSIVE on both ends: equal `start` and `end` return that
    day. Oura does not behave that way — some collections exclude the last day
    and others don't, and `workout` is skewed to UTC — but that is corrected
    here.

    Date-range collections use YYYY-MM-DD. `heartrate` and `ring_battery_level`
    use ISO 8601 with time. `personal_info` and `ring_configuration` take no
    range.
    """
    if collection not in COLLECTIONS:
        return {"error": f"«{collection}» is not an Oura collection",
                "available": sorted(COLLECTIONS)}
    if day:
        # "A single day" is the most common query and the one that was broken.
        # Making the common path not require a range is half the fix; the other
        # half is already in the client.
        if start or end:
            return {"error": "use `day`, or `start` and `end`, but not both"}
        start = end = day
    if shape(collection) in WITH_DATE and not latest and not (start and end):
        return {"error": f"{collection} needs `start` and `end`",
                "format": "YYYY-MM-DD" if shape(collection) == "date_range" else "ISO 8601 with time"}
    try:
        if format not in ("json", "csv"):
            return {"error": f"format «{format}» does not exist; there is `json` and `csv`"}
        return fetch(collection, start, end, fields=fields, latest=latest,
                       format=format)
    except OuraError as e:
        # Returned as data, not raised: an exception cuts the whole conversation
        # short over what is almost always a malformed date or an expired token.
        return {"error": str(e)}


@server.tool(title="Self-check of the Oura connection",
               annotations=ToolAnnotations(title="Self-check of the Oura connection",
                                           **_SOLO_LECTURA))
def oura_check() -> dict:
    """Self-check: is there a credential, and does Oura respond? Exposing nothing.

    Returns neither the token nor any health value. It reports the token's
    LENGTH, never the token: diagnostic messages are the ones most often copied
    into chats and issues.
    """
    return check()


def _modo_de_autenticacion() -> str:
    """Which credential is in use, in the same order `_token()` decides."""
    if os.environ.get("OURA_PAT_FILE"):
        return "personal token (OURA_PAT_FILE)"
    if os.environ.get("OURA_PAT"):
        return "personal token (OURA_PAT)"
    return "OAuth2"


def _estado_de_oauth() -> dict:
    """Alcances y caducidad, SIN un solo token.

    The scopes answer the question people ask most when something comes back
    empty: "is there no data, or did I not grant permission?". Oura answers that
    difference with a 403 that isn't always distinguishable from a range with no
    records, so having them at hand saves the wrong diagnosis.
    """
    if os.environ.get("OURA_PAT_FILE") or os.environ.get("OURA_PAT"):
        return {}
    try:
        from .credentials import SCOPES, load
        cred = load()
    except OuraError as e:
        return {"credenciales": f"unreadable: {e}"}
    if cred is None:
        return {}
    import time
    faltan = int(cred.expires_at - time.time())
    fuera = sorted(set(SCOPES) - set(cred.scopes))
    return {
        "granted_scopes": list(cred.scopes),
        "ungranted_scopes": fuera,
        "access_expires_in_seconds": faltan,
        "refreshes_itself": cred.refresh_token is not None,
    }


def check() -> dict:
    """Same as the tool, but callable from the command line."""
    from .client import _token, base, in_sandbox
    if in_sandbox():
        # In sandbox there is no token to check and it mustn't look like there
        # is: whoever reads this response has to know the data is made up.
        out: dict = {"mode": "sandbox", "data": "synthetic, from Oura, not yours",
                     "base": base()}
        try:
            # The pulse CANNOT be `personal_info`: it is the only one of the 19
            # the sandbox does not serve. That makes sense — it's the one
            # returning email, age, weight and height — but it means something
            # else has to be asked here, or the self-check reports an API as down
            # when it is up.
            r = fetch("daily_sleep", "2026-01-01", "2026-01-03")
            out["oura_responds"] = True
            out["sample_fields"] = sorted(r["data"][0]) if r["data"] else []
        except OuraError as e:
            out["oura_responds"] = False
            out["error"] = str(e)
        out["unavailable_in_sandbox"] = ["personal_info"]
        out["next_step"] = ("drop OURA_SANDBOX and set your own credential to see "
                                 "your data")
        return out
    try:
        t = _token()
    except OuraError as e:
        return {"token_present": False, "next_step": str(e)}
    out: dict = {
        "token_present": True,
        "token_length": len(t),
        "mode": _modo_de_autenticacion(),
    }
    out.update(_estado_de_oauth())
    try:
        r = fetch("personal_info")
        out["oura_responds"] = True
        # The field NAMES, not their values: confirms the API answers without
        # dumping anyone's profile into a log.
        out["profile_fields"] = sorted(r["data"][0]) if r["data"] else []
    except OuraError as e:
        out["oura_responds"] = False
        out["error"] = str(e)
    return out


async def main() -> None:
    await server.run_stdio_async()
