"""The public surface is frozen here, and changing it means changing this file.

FOUR CLASSES OF NAME HAVE BROKEN, ONE AT A TIME, EACH FOUND BY A HUMAN:

    CLI flags         `--autorizar` survived the translation; twelve commands in
                      the documentation answered "I don't know --revisar".
    response keys     `campos_ignorados` and three others stayed documented after
                      the code stopped emitting them.
    tool parameters   the README's table still read `dia`, `inicio`, `campos`,
                      and llms.txt asserted outright that parameters were in
                      Spanish. Oscar pasted it back as evidence.
    return values     the catalog returned `que_trae`, and the two
                      implementations described themselves as `date_range` and
                      `dateRange` — the same server answering differently
                      depending on which one you installed.

Every guard was written AFTER the class it watches had already broken, and none
of them generalized. So this file stops guessing which class breaks next and
pins the whole surface instead: rename anything a client can see and this test
fails until someone writes the new name down on purpose.

That is the point. These names are a promise to people who have already
installed the thing — a rename is a decision, not a refactor, and it should cost
one deliberate edit.

IT NEVER TOUCHES THE NETWORK. Everything is read statically or from an import;
nothing is called, because calling `oura_check` would reach Oura's sandbox.
"""

import inspect
import pathlib
import re

import pytest

from oura_mcp import server as S
from oura_mcp.__main__ import ACTIONS, MODIFIERS

ROOT = pathlib.Path(__file__).parent.parent


# ── The frozen surface ─────────────────────────────────────────────────────
TOOLS = {"oura_collections", "oura_query", "oura_check"}

PARAMETERS = {
    "oura_collections": set(),
    "oura_check": set(),
    "oura_query": {"collection", "start", "end", "day", "fields", "latest", "format"},
}

# Everything `client.py` can put in a response.
RESPONSE_KEYS = {
    "collection", "n", "pages", "data",           # always
    "format", "columns", "uneven_columns",        # csv
    "truncated", "continue_from", "pagination_cycle",
    "ignored_fields", "fields_split", "large_response",
    "discarded_out_of_range", "empty", "synthetic", "rate_limited",
}

# Everything `server.py` adds on top, in `oura_check` and the error paths.
SERVER_KEYS = {
    "error", "next_step", "oura_responds", "profile_fields",
    "sample_fields", "unavailable_in_sandbox",
}

FLAGS = {"--help", "-h", "--check", "--authorize", "--forget", "--manual"}

RESOURCES = {"oura://collections"}


def _keys_in(path: str) -> set[str]:
    return set(re.findall(r'out\["([a-z_]+)"\]', (ROOT / path).read_text(encoding="utf-8")))


# ── The locks ──────────────────────────────────────────────────────────────
def test_the_tools_are_exactly_these_three():
    exposed = {n for n in dir(S) if n.startswith("oura_")}
    assert exposed == TOOLS


@pytest.mark.parametrize("tool", sorted(TOOLS))
def test_each_tool_takes_exactly_these_parameters(tool):
    fn = getattr(S, tool)
    fn = getattr(fn, "fn", fn)
    assert set(inspect.signature(fn).parameters) == PARAMETERS[tool]


def test_the_response_keys_are_exactly_these():
    """`out[...]` in client.py — every warning and every field a caller reads."""
    found = _keys_in("src/oura_mcp/client.py")
    assert found <= RESPONSE_KEYS, f"new key(s), write them down: {found - RESPONSE_KEYS}"
    # `n`, `pages` and friends are set in the dict literal, not through `out[…]`,
    # so the reverse check is deliberately one-directional.


def test_the_server_keys_are_exactly_these():
    found = _keys_in("src/oura_mcp/server.py")
    assert found <= SERVER_KEYS, f"new key(s), write them down: {found - SERVER_KEYS}"


def test_the_cli_flags_are_exactly_these():
    assert set(ACTIONS) | set(MODIFIERS) == FLAGS


def test_the_resource_uris_are_exactly_these():
    src = (ROOT / "src" / "oura_mcp" / "server.py").read_text(encoding="utf-8")
    assert set(re.findall(r'@server\.resource\("([^"]+)"', src)) == RESOURCES


def test_the_typescript_surface_matches():
    """The `.mcpb` ships TypeScript and PyPI ships Python. A name that exists in
    one and not the other makes the documentation right for half the users, and
    that has already happened twice — `rate_limited` and `fields_split` both
    landed in Python first and were caught here rather than by a reader."""
    ts = (ROOT / "ts" / "src" / "client.ts").read_text(encoding="utf-8")
    assert set(re.findall(r'out\["([a-z_]+)"\]', ts)) == _keys_in("src/oura_mcp/client.py")

    ts_server = (ROOT / "ts" / "src" / "server.ts").read_text(encoding="utf-8")
    assert set(re.findall(r'"(oura://[^"]+)"', ts_server)) == RESOURCES


# ── Messages are surface too ───────────────────────────────────────────────
SPANISH_MARKERS = ("no se ", " pudo ", "archivo", "vacío", "vacio", " desde ",
                   " hasta ", "porque", "credencial", "está ", " para ",
                   "fallo", "no hay ")


def _user_facing_strings(path: str) -> list[str]:
    """Strings that reach a person: raised errors and printed lines."""
    src = (ROOT / path).read_text(encoding="utf-8")
    out = []
    for m in re.finditer(r'(?:OuraError|RuntimeError|ValueError|print)\(\s*\n?\s*f?["`]([^"`]{10,})', src):
        out.append(m.group(1))
    return out


@pytest.mark.parametrize("path", [
    "src/oura_mcp/client.py", "src/oura_mcp/credentials.py",
    "src/oura_mcp/authorize.py", "src/oura_mcp/server.py",
    "ts/src/client.ts", "ts/src/credentials.ts", "ts/src/authorize.ts",
])
def test_no_error_message_is_in_spanish(path):
    """Three survived the translation — `no se pudo alcanzar Oura` in Python and
    two more in TypeScript — in the place a person is most likely to read: an
    error, while already stuck.

    Comments and internal names can lag. A message cannot: it is the surface,
    same as a key or a parameter, and the translation was announced as complete.
    """
    if not (ROOT / path).exists():
        pytest.skip(f"{path} does not exist")
    for text in _user_facing_strings(path):
        low = text.lower()
        for marker in SPANISH_MARKERS:
            assert marker not in low, f"{path}: «{text[:70]}»"


def test_the_keychain_account_name_is_not_renamed():
    """`_KEYCHAIN_ACCOUNT` is "credenciales" and MUST STAY.

    It is a storage key, not a message. Anyone who authorized before the
    translation has their refresh token filed under this exact string, and
    renaming it would orphan those credentials silently: `load()` finds nothing
    and asks them to authorize again with no explanation, while the old secret
    stays in their keychain forever.

    Translating a repository means translating what people read, not what
    machines look things up by. This test exists because those two are easy to
    confuse when sweeping for leftover Spanish — as the sweep that found the
    error messages nearly did.
    """
    from oura_mcp.credentials import _KEYCHAIN_ACCOUNT, _KEYCHAIN_SERVICE
    assert _KEYCHAIN_ACCOUNT == "credenciales"
    assert _KEYCHAIN_SERVICE == "oura-mcp"
