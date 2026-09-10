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
import typing

import pytest

from oura_mcp import server as S
from oura_mcp.__main__ import ACTIONS, MODIFIERS

ROOT = pathlib.Path(__file__).parent.parent


# ── The frozen surface ─────────────────────────────────────────────────────
TOOLS = {"oura_collections", "oura_query", "oura_check", "oura_today"}

PARAMETERS = {
    "oura_collections": set(),
    "oura_check": set(),
    "oura_query": {"collection", "start", "end", "day", "fields", "latest", "format"},
    "oura_today": {"days"},
}

# Everything `client.py` can put in a response.
RESPONSE_KEYS = {
    "collection", "n", "pages", "data",           # always
    "format", "columns", "uneven_columns",        # csv
    "truncated", "continue_from", "pagination_cycle",
    "ignored_fields", "fields_split", "large_response",
    "discarded_out_of_range", "empty", "synthetic", "rate_limited",
    "cached",                                     # answered from memory
}

# Everything `server.py` adds on top, in `oura_check` and the error paths.
SERVER_KEYS = {
    "error", "next_step", "oura_responds", "profile_fields",
    "sample_fields", "unavailable_in_sandbox",
    # oura_today
    "today", "days", "computed", "sleep", "readiness", "missing", "records",
}

FLAGS = {"--help", "-h", "--check", "--authorize", "--forget", "--manual"}

RESOURCES = {"oura://collections"}


def _keys_in(path: str) -> set[str]:
    return set(re.findall(r'out\["([a-z_]+)"\]', (ROOT / path).read_text(encoding="utf-8")))


def _literal_keys_in(path: str) -> set[str]:
    """Keys written straight into a returned dict literal.

    THE LOCK HAD A BLIND SPOT. Written to be general, it only read `out[...]`
    assignments — and `_oauth_state` returned `{"credenciales": ...}` from a
    literal, so a Spanish key sat in a user-facing diagnostic one round after
    the guard that was supposed to make that impossible.

    A guard is only as general as the shapes it knows how to look at.
    """
    src = (ROOT / path).read_text(encoding="utf-8")
    keys: set[str] = set()
    for block in re.findall(r"return \{(.*?)\}", src, re.S):
        keys |= set(re.findall(r'"([a-z_]{3,})":', block))
    return keys


# ── The locks ──────────────────────────────────────────────────────────────
def test_the_declared_list_matches_the_real_one():
    """`TOOLS_EXPUESTAS` is what the documentation guard counts. If it drifts
    from what the server actually registers, that guard starts defending a
    number nobody exposes — which is the exact way its predecessor failed."""
    from oura_mcp.server import TOOLS_EXPUESTAS
    assert set(TOOLS_EXPUESTAS) == TOOLS
    assert len(TOOLS_EXPUESTAS) == len(set(TOOLS_EXPUESTAS)), "a name is repeated"


def test_the_tools_are_exactly_these_four():
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
                   "fallo", "no hay ",
                   # Added after «${collection} necesita start y end` shipped in
                   # the bundle for four releases. The list only ever knows the
                   # vocabulary of the last bug, which is why the real guard is
                   # test_both_implementations_describe_every_parameter_identically
                   # — comparison, not vocabulary. These stay as a cheap net.
                   "necesita", "con hora", "aaaa-mm-dd")


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
    # server.ts was the one file missing from this list, and it was the file
    # holding the Spanish. Python listed all four of its modules; TypeScript
    # listed three of four.
    "ts/src/server.ts",
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


def test_both_implementations_say_the_same_thing_first():
    """The instructions travel in every session and are the only text a model
    reads before deciding what to do. They drifted once already — `synthetic`
    was absent from both — so the lead line is pinned in both languages."""
    lead = "BEFORE ANYTHING ELSE"
    for f in ("src/oura_mcp/server.py", "ts/src/server.ts"):
        text = (ROOT / f).read_text(encoding="utf-8")
        assert lead in text, f
        assert "NOT this person's" in text, f


def test_no_dict_literal_returns_a_spanish_key():
    """The blind spot in the lock itself: `{"credenciales": ...}` in a returned
    literal, one round after the guard meant to make that impossible."""
    for path in ("src/oura_mcp/server.py", "src/oura_mcp/client.py",
                 "src/oura_mcp/credentials.py", "src/oura_mcp/authorize.py"):
        for key in _literal_keys_in(path):
            for marker in ("credenciales", "coleccion", "paginas", "campos",
                           "modo", "alcances", "caducidad", "vacio", "archivo"):
                assert key != marker, f"{path} returns a key named `{key}`"


def test_the_credentials_filename_is_documented_correctly():
    """`credenciales.json` is a STORAGE PATH, and it stays.

    Same reasoning as the keychain account name: anyone who authorized before
    the translation has their refresh token in that exact file, and renaming it
    orphans them silently. What must be true is that the documentation names the
    real file.

    It didn't. The README got it right and two places got it wrong: the `.mcpb`
    manifest — the text someone reads in Claude Desktop's settings while
    configuring this very path — and SUBMISSION.md, which is a factual claim
    about where credentials live, written for a directory reviewer. A privacy
    statement naming a file that does not exist is worse than a stale README.
    """
    from oura_mcp.credentials import credentials_path
    import os
    os.environ.pop("OURA_CREDENTIALS", None)
    real = os.path.basename(credentials_path())
    assert real == "credenciales.json"

    for f in ("README.md", "SUBMISSION.md", "ts/manifest.json"):
        path = ROOT / f
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        if "oura-mcp/" in text and ".json" in text:
            assert "oura-mcp/credentials.json" not in text, \
                f"{f} names a credentials file that does not exist"


def test_both_implementations_write_to_the_same_file():
    """If they diverged, `oura-mcp --authorize` from PyPI would leave the
    `.mcpb` saying «no credentials» — two halves of one product refusing to see
    each other's work."""
    ts = (ROOT / "ts" / "src" / "credentials.ts").read_text(encoding="utf-8")
    py = (ROOT / "src" / "oura_mcp" / "credentials.py").read_text(encoding="utf-8")
    assert '"oura-mcp", "credenciales.json"' in ts
    assert '"oura-mcp", "credenciales.json"' in py


def test_the_no_credentials_message_serves_both_audiences():
    """It was written for someone with a terminal, and the flagship install path
    doesn't have one.

    Whoever installed the `.mcpb` has no `oura-mcp` command anywhere — the bundle
    ships node and a dist directory, nothing on the PATH — and `OURA_SANDBOX=1`
    is a checkbox in their settings, not an environment variable. Both
    instructions were unfollowable for exactly the people most likely to read
    them, which is the same failure round 11 found in the cold-start errors: a
    fix that cannot be applied is not a fix.

    The checkbox is quoted by its real title, so renaming it in the manifest
    without updating this breaks here rather than in front of someone stuck.
    """
    import json as _json
    manifest = _json.loads((ROOT / "ts" / "manifest.json").read_text(encoding="utf-8"))
    titulo = manifest["user_config"]["sandbox"]["title"]

    for f in ("src/oura_mcp/client.py", "ts/src/client.ts"):
        text = (ROOT / f).read_text(encoding="utf-8")
        i = text.find("no credentials. Three paths")
        assert i != -1, f
        block = text[i:i + 1400]
        assert "extension" in block, f"{f}: no route for the extension user"
        assert "Use sample data" in block, f"{f}: the checkbox is not named"
        assert "terminal" in block, f"{f}: the terminal route disappeared"
        assert titulo.startswith("Use sample data"), \
            "the manifest renamed the checkbox; the message now points at nothing"


def test_no_parameter_description_is_in_spanish():
    """A FIFTH VOCABULARY. The lock pins NAMES, and the `collection` parameter's
    DESCRIPTION still read «Nombre exacto. Ver `oura_collections`.» — sent to
    every client in `tools/list`, in both implementations.

    Four classes of name broke one at a time and each guard was written after the
    fact; descriptions were the class nobody had thought of yet. Same shape,
    found by asking what else a client can see.
    """
    marcadores = ("Nombre", "exacto", "Ver `", "colección", "obligatorio",
                  "opcional", "sólo", "Devuelve")
    for f in ("src/oura_mcp/server.py", "ts/src/server.ts"):
        text = (ROOT / f).read_text(encoding="utf-8")
        for m in re.finditer(r'(?:description=|\.describe\()"([^"]{8,})"', text):
            for marcador in marcadores:
                assert marcador not in m.group(1), f"{f}: «{m.group(1)[:60]}»"


def _descriptions_in(hint):
    """Every `Field(description=...)` reachable from an annotation.

    It RECURSES, and that is the whole point. Up to 3.10 `get_type_hints`
    re-wrapped any parameter defaulting to None as `Optional[Annotated[...]]`,
    so `__metadata__` sits one level in; 3.11 dropped that implicit wrap and it
    sits at the top. Reading only the top level passes on a modern interpreter
    and silently sees four fewer parameters on the 3.10 floor — which is what
    the first version of this test did, green here and red in CI.
    """
    for meta in getattr(hint, "__metadata__", ()):
        texto = getattr(meta, "description", None)
        if texto:
            yield texto
    for arg in typing.get_args(hint):
        yield from _descriptions_in(arg)


def _python_parameter_descriptions(tool: str) -> dict[str, str]:
    """name -> description, read off the real signature, not off the text."""
    fn = getattr(S, tool)
    fn = getattr(fn, "fn", fn)
    out = {}
    for name, hint in typing.get_type_hints(fn, include_extras=True).items():
        for texto in _descriptions_in(hint):
            out[name] = texto
    return out


def test_the_description_reader_sees_through_an_optional_wrap():
    """Pins the 3.10 shape directly, so the reader cannot regress to top-level
    only on an interpreter where that happens to work."""
    from pydantic import Field as _F
    envuelto = typing.Optional[typing.Annotated[str, _F(description="ahi esta")]]
    assert list(_descriptions_in(envuelto)) == ["ahi esta"]


_TS_PARAM = re.compile(
    r'^ {6}(\w+):\s*z\.[^\n]*?\.describe\(\s*'
    r'((?:"(?:[^"\\]|\\.)*"\s*\+?\s*)+)\)', re.M | re.S)


def _typescript_parameter_descriptions(tool: str) -> dict[str, str]:
    """The same map, parsed out of ONE tool's `inputSchema` block.

    Scoped per tool rather than per file. The first version read the whole of
    server.ts into a single map, which happened to work while `oura_query` was
    the only tool with parameters and would have silently merged two tools'
    schemas the moment a second one had a name in common.
    """
    text = (ROOT / "ts" / "src" / "server.ts").read_text(encoding="utf-8")
    inicio = text.index(f'srv.registerTool("{tool}"')
    siguiente = text.find("srv.registerTool(", inicio + 1)
    bloque = text[inicio:siguiente if siguiente != -1 else len(text)]
    out = {}
    for m in _TS_PARAM.finditer(bloque):
        trozos = re.findall(r'"((?:[^"\\]|\\.)*)"', m.group(2))
        out[m.group(1)] = "".join(trozos)
    return out


def test_both_implementations_describe_every_parameter_identically():
    """A SIXTH VOCABULARY, and the last one this guard will ever need.

    Every Spanish sweep before this one was a word list, and a word list only
    knows the vocabulary of the bug that prompted it. `test_no_parameter_
    description_is_in_spanish` scans this exact file with the right regex and
    passed anyway, because «AAAA-MM-DD, o ISO 8601 con hora» contains not one
    of its eight markers. The bundle shipped it to every client in
    `tools/list` for four releases.

    Descriptions are the only text a model reads before deciding how to call a
    tool, and the `.mcpb` ships the TypeScript ones. So stop guessing at
    vocabulary and compare the two sides: they answer the same question and
    must say so with the same words. This needs no marker list and cannot go
    stale.

    It found four when it was written, and only two were Spanish. `fields` had
    quietly dropped `heartrate`, and `format` had lost the entire reason to
    prefer CSV — the ~37,000 records whose keys repeat — leaving the half that
    ships in the bundle unable to explain its own advice.
    """
    for tool in sorted(TOOLS):
        esperado = _python_parameter_descriptions(tool)
        obtenido = _typescript_parameter_descriptions(tool)
        assert set(esperado) == set(obtenido), (
            f"{tool} declares different parameters:\n"
            f"  python:     {sorted(esperado)}\n"
            f"  typescript: {sorted(obtenido)}")
        for nombre in sorted(esperado):
            assert obtenido[nombre] == esperado[nombre], (
                f"{tool}.`{nombre}` is described differently:\n"
                f"  python:     {esperado[nombre]}\n"
                f"  typescript: {obtenido[nombre]}")


def _returned_keys(path: str) -> set[str]:
    """Keys of every object literal handed back by a `return {...}`.

    Reads BOTH languages: Python quotes its keys, TypeScript does not. The
    older `_literal_keys_in` only knew the quoted shape, so every object
    TypeScript returns was invisible to it — which is how a key spelled
    `alcances_concedidos` sat in the bundle's OAuth result unguarded.
    """
    src = (ROOT / path).read_text(encoding="utf-8")
    keys: set[str] = set()
    for block in re.findall(r"return \{(.*?)\n\s*\}", src, re.S):
        keys |= set(re.findall(r'^\s*"?([a-z_]{3,})"?\s*:', block, re.M))
    return keys


def test_the_authorize_result_has_the_same_keys_in_both():
    """The OAuth result is the last thing a person sees before the server works,
    and it is returned from an object literal — the one shape every guard here
    was blind to on the TypeScript side.

    `test_no_dict_literal_returns_a_spanish_key` iterates four Python modules
    and no TypeScript at all, and compares each key for EQUALITY against a
    marker list that does contain «alcances» — which `alcances_concedidos` is
    not equal to. Two independent reasons to miss the same key.

    Comparing the two implementations needs neither a file list nor a
    vocabulary: whatever one returns, the other must return under the same
    name.
    """
    py = _returned_keys("src/oura_mcp/authorize.py")
    ts = _returned_keys("ts/src/authorize.ts")
    solo_py, solo_ts = py - ts, ts - py
    assert not solo_py and not solo_ts, (
        f"the OAuth result differs:\n  only python:     {sorted(solo_py)}\n"
        f"  only typescript: {sorted(solo_ts)}")


def test_the_typescript_handshake_reports_the_real_version():
    """It said 0.3.0 while everything else said 0.3.2, and it is the number the
    MCP handshake reports — so the bundle told every client a version that had
    not existed for two releases.

    The same bug the audit fixed in Python, recurring in the half that ships in
    the `.mcpb`, because the coherence test pinned the manifest and package.json
    and not this constant. It is read from package.json now, so there is nothing
    left to drift.
    """
    ts = (ROOT / "ts" / "src" / "server.ts").read_text(encoding="utf-8")
    assert 'export const VERSION = "' not in ts, "the version is hand-typed again"
    assert "package.json" in ts, "it no longer reads the version from anywhere"


def test_the_server_carries_an_embedded_icon():
    """In a registry with ~8 Oura entries a client picker renders icons, and the
    512×512 PNG already existed for the `.mcpb`.

    EMBEDDED, not linked. An `https://…` icon makes every client fetch it from
    GitHub on every session — a request telling a third party «somebody is using
    this right now», from a health server that promises no telemetry. 16 KB down
    a local pipe, once, is the cheaper end of that trade.
    """
    from oura_mcp.server import _icon

    iconos = _icon()
    assert len(iconos) == 1
    src = iconos[0].src
    assert src.startswith("data:image/png;base64,"), "the icon is fetched, not carried"
    assert "http" not in src.split(",", 1)[1][:200], "an external URL crept in"


def test_the_icon_ships_inside_the_installed_package():
    """It lives next to the code, not only in the repository: a `pip install`
    that leaves it behind would silently drop the icon for everyone who didn't
    clone."""
    import json as _json
    assert (ROOT / "src" / "oura_mcp" / "icon.png").exists()
    texto = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "icon.png" in texto, "setuptools will not package it"
    # And the TypeScript half must find it from the packed layout too.
    ts = (ROOT / "ts" / "src" / "server.ts").read_text(encoding="utf-8")
    assert "../icon.png" in ts and "../../icon.png" in ts, \
        "only one layout is tried; the bundle puts it at a different depth"
    _json  # noqa: B018
