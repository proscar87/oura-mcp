"""The files that repeat each other must not contradict each other.

THEY NEVER TOUCH THE NETWORK. They only read files from the repository.

The version is declared in SIX places — pyproject, server.json twice,
plugin.json, marketplace.json, and the MCP handshake's `serverInfo` — and they
drift apart silently. It already happened: the server announced itself as 0.1.0
while `pyproject.toml` was at 0.2.0, and a stdio smoke test caught it, not the
function tests. The number a client sees comes from the handshake, which no
function test looks at.

A server that lies about its version makes the most common question in a bug
report impossible to answer: "do you have the one with the fix?"
"""

import json
import pathlib
import re

ROOT = pathlib.Path(__file__).parent.parent


def _read_json(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def _declared_version() -> str:
    """The version from `pyproject.toml`, read with a regular expression.

    `tomllib` is Python 3.11 and this package declares 3.10 as its minimum. Using
    it here would have made the coherence test break CI on precisely the oldest
    version we claim to support — which is exactly the kind of incoherence this
    file exists to catch.
    """
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    assert m, "pyproject.toml has no `version`"
    return m.group(1)


# ── The version, everywhere ────────────────────────────────────────────────
def test_server_json_matches_pyproject():
    """The MCP registry validates that the exact version exists on PyPI. If they
    don't match, publication fails halfway: the package uploads and the registry
    rejects it."""
    v = _declared_version()
    s = _read_json("server.json")
    assert s["version"] == v
    assert s["packages"][0]["version"] == v


def test_the_plugin_matches_pyproject():
    v = _declared_version()
    assert _read_json(".claude-plugin/plugin.json")["version"] == v
    assert _read_json(".claude-plugin/marketplace.json")["plugins"][0]["version"] == v


def test_the_handshake_announces_the_installed_version():
    from oura_mcp.server import _version
    assert _version() != "unknown"


# ── What the registry demands and is easy to delete by accident ────────────
def test_the_readme_keeps_the_ownership_proof():
    """The MCP registry checks that whoever publishes the server controls the
    package by looking for this line in the README published to PyPI. Without it,
    `mcp-publisher publish` returns a 400."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    name = _read_json("server.json")["name"]
    assert f"mcp-name: {name}" in readme


def test_the_readme_carries_the_privacy_policy():
    """Claude's connectors directory rejects immediately if it's missing or
    incomplete. It has to cover six things.

    The README is in English — it's what a stranger reads and what a directory
    reviewer reads — so the terms searched for here are the English ones.
    """
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "## Privacy Policy" in readme
    for topic in ("What is collected", "What is stored", "shared with",
                  "retained", "Contact"):
        assert topic in readme, topic


def test_the_description_fits_the_registry():
    """The MCP registry caps `description` at 100 characters. v0.2.0 was
    published to PyPI and then failed the registry over six characters too
    many — with PyPI already uploaded, which is the irreversible half."""
    d = _read_json("server.json")["description"]
    assert len(d) <= 100, f"{len(d)} characters: {d}"


def test_the_server_name_fits():
    """Same cap, same family; better to find out here."""
    assert len(_read_json("server.json")["name"]) <= 200


# ── The documentation must not contradict itself ───────────────────────────
def _docs() -> dict[str, str]:
    """The documents, with quoted text stripped out.

    ASSERTING IS NOT QUOTING. These files record claims that expired — "four
    tools", "the most complete one doesn't paginate" — precisely so nobody
    repeats them, and a test that can't tell the two apart fires on the
    explanation of its own rule. That happened on the first run.

    Both quote styles are stripped: the angle quotes this repository used while
    it was in Spanish, and the straight quotes the English documents use.
    """
    docs = {}
    for n in ("README.md", "AGENTS.md", "ROADMAP.md", "CHANGELOG.md", "llms.txt"):
        text = (ROOT / n).read_text(encoding="utf-8")
        text = re.sub(r"«[^»]*»", "«…»", text)
        # Bounded and across newlines: quotes in prose wrap, and a quote that
        # wraps is still a quote.
        text = re.sub(r'"[^"]{0,220}"', '"…"', text, flags=re.S)
        docs[n] = text
    return docs


def test_the_source_does_not_repeat_the_phrase_either():
    """The test below only looked at the documents, and the phrase also lived in
    `client.py`'s docstring. Comments age exactly like a README and mislead
    exactly as much — with the difference that nobody rereads them."""
    for f in (ROOT / "src" / "oura_mcp").glob("*.py"):
        text = re.sub(r"«[^»]*»", "«…»", f.read_text(encoding="utf-8"))
        assert "most complete one doesn't paginate" not in text, f.name
        assert "más completo de todos no pagina" not in text, f.name


def test_no_document_repeats_the_phrase_that_stopped_being_true():
    """"The most complete one doesn't paginate" was true and stopped being:
    benngermin/oura-mcp paginates, with a resumable cursor. A claim about the
    competition that anyone can verify in a minute is the most expensive one to
    leave rotting."""
    for name, text in _docs().items():
        assert "más completo de todos no pagina" not in text, name
        assert "most complete one doesn't paginate" not in text, name


def test_no_document_promises_four_tools():
    """There are three, and there always have been."""
    for name, text in _docs().items():
        assert "cuatro herramientas" not in text.lower(), name
        assert "four tools" not in text.lower(), name


def test_the_collection_count_matches_everywhere():
    from oura_mcp.collections import COLLECTIONS
    assert len(COLLECTIONS) == 19
    for name, text in _docs().items():
        for wrong in ("18 collections", "20 collections", "18 colecciones",
                      "20 colecciones"):
            assert wrong not in text, f"{name}: {wrong}"


def test_the_measurements_are_quoted_the_same_everywhere():
    """1,231 samples across 2 pages. It's a measured number; copied wrong into
    another file, the next person doesn't know which to believe."""
    for name, text in _docs().items():
        if "1,231" in text or "1231" in text:
            assert any(x in text for x in ("2 pages", "two-page", "2 páginas")), \
                f"{name} cites the samples without the page count"
        # No document may carry the old estimate as though it were measured.
        assert "1,250 muestras en 2 páginas" not in text, name
        assert "1,250 samples" not in text, name


def test_the_outward_facing_files_are_in_english():
    """README and llms.txt are the first thing a stranger sees and what a Claude
    directory reviewer reads."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    llms = (ROOT / "llms.txt").read_text(encoding="utf-8")
    for text, name in ((readme, "README.md"), (llms, "llms.txt")):
        for leftover in ("## Instalación", "## Las herramientas", "## Licencia",
                         "## El problema"):
            assert leftover not in text, f"{name} still has {leftover}"
    assert "## License" in readme


def test_no_document_sends_you_to_create_a_personal_token():
    """Oura stopped issuing them in December 2025. Pointing someone at that page
    leaves them stuck without knowing why."""
    for name, text in _docs().items():
        if "personal-access-tokens" in text:
            # Only allowed when accompanied by the warning.
            assert "December 2025" in text or "diciembre de 2025" in text, \
                f"{name} points at the page without warning"
