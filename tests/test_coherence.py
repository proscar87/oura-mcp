"""The files that repeat each other must not contradict each other.

THEY NEVER TOUCH THE NETWORK. They only read files from the repository.

The version is declared in TEN places — pyproject, server.json twice,
plugin.json, marketplace.json twice, ts/package.json, ts/manifest.json,
package-lock.json twice — plus `__version__` and the MCP handshake's
`serverInfo`, which are read rather than typed so they cannot drift. It said SIX
here while four of the ten went unpinned, and two of those four had already
drifted. They drift apart silently. It already happened: the server announced itself as 0.1.0
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
    """`marketplace.json` declares the version TWICE — once in `metadata`, once in
    the plugin entry — and this test pinned only the second for three releases."""
    v = _declared_version()
    assert _read_json(".claude-plugin/plugin.json")["version"] == v
    mk = _read_json(".claude-plugin/marketplace.json")
    assert mk["plugins"][0]["version"] == v
    assert mk["metadata"]["version"] == v


def test_the_lockfile_matches_pyproject():
    """`npm install` rewrites the lockfile from `package.json`, so nobody edits it
    by hand and nobody read it either: it said 0.3.0 while everything else said
    0.3.2, two releases behind, and no test looked. It is what `npm ci` installs
    in the TypeScript job, and it declares the version in two places."""
    v = _declared_version()
    lock = _read_json("ts/package-lock.json")
    assert lock["version"] == v
    assert lock["packages"][""]["version"] == v


def test_the_package_does_not_hand_type_its_version():
    """`oura_mcp.__version__` said 0.1.0 while `pyproject.toml` was at 0.3.2 — the
    conventional way to ask a Python package what it is, answering with a version
    retired three releases earlier. Nothing caught it because nothing read it.

    Read from `importlib.metadata`, never typed, which is the fix the handshake
    got in Python and `VERSION` got in TypeScript. Asserted as «no literal
    version is assigned» rather than pinning a number, so the guard cannot go
    stale the way the thing it guards did."""
    text = (ROOT / "src" / "oura_mcp" / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r'__version__\s*=\s*"\d', text)
    assert not m, "the version is hand-typed again"
    assert "importlib.metadata" in text, "it no longer reads the version from anywhere"

    import oura_mcp
    assert oura_mcp.__version__ == _declared_version()


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


def test_the_mcpb_manifest_matches_pyproject():
    """The bundle declares its own version, and Claude Desktop shows that one.
    A `.mcpb` claiming a version the package never published makes a bug report
    impossible to place."""
    m = _read_json("ts/manifest.json")
    assert m["version"] == _declared_version()
    assert _read_json("ts/package.json")["version"] == _declared_version()


def test_the_mcpb_declares_the_three_tools():
    """The directory review syncs tools from the manifest. Declaring a tool the
    server doesn't expose — or missing one it does — is caught here rather than
    by a reviewer."""
    from oura_mcp.collections import COLLECTIONS  # noqa: F401  (import guard)
    declared = {t["name"] for t in _read_json("ts/manifest.json")["tools"]}
    assert declared == {"oura_collections", "oura_query", "oura_check"}


def test_the_mcpb_carries_a_privacy_policy_url():
    """«Missing or incomplete privacy policies result in immediate rejection.»"""
    urls = _read_json("ts/manifest.json")["privacy_policies"]
    assert urls and all(u.startswith("https://") for u in urls)


def test_the_sample_data_checkbox_warns_in_its_title():
    """The sandbox default is ON, so someone who reads nothing gets Oura's
    made-up numbers on their first question. That's only acceptable because
    every response carries the `synthetic` key — see test_sandbox_marker.py.

    The title is the one string a non-reader does see, so it has to carry the
    warning by itself; the description below it is already optional reading.
    """
    cfg = _read_json("ts/manifest.json")["user_config"]["sandbox"]
    assert cfg["default"] is True, \
        "if the default changes, revisit whether a fresh install still works"
    assert "NOT your own" in cfg["title"], cfg["title"]


def test_both_languages_word_the_marker_the_same():
    """Python and TypeScript are two implementations of one promise. A marker
    that says different things depending on which one you installed is the same
    drift the version test exists to catch, on the string that matters most."""
    py = (ROOT / "src" / "oura_mcp" / "client.py").read_text(encoding="utf-8")
    ts = (ROOT / "ts" / "src" / "client.ts").read_text(encoding="utf-8")
    for fragment in ("SANDBOX MODE: this is Oura's sample data, not this person's",
                     "sample-data setting and connect an Oura account"):
        assert fragment in py, f"client.py: {fragment}"
        assert fragment in ts, f"client.ts: {fragment}"


def test_the_docs_only_cite_flags_the_cli_accepts():
    """A command in a README is an instruction, and one that doesn't exist wastes
    someone's afternoon before they conclude the package is broken.

    The flags were renamed to English and the documents kept the old ones: twelve
    commands across README, llms.txt and AGENTS.md that answered
    `I don't know --revisar`. The rename was recorded for the tool parameters and
    not for the CLI, so nothing caught it.

    CHANGELOG.md is excluded on purpose: its 0.2.0 entry describes a release
    whose flags really were Spanish. Rewriting history to satisfy a test would
    make the changelog lie about what was shipped.
    """
    from oura_mcp.__main__ import ACTIONS, MODIFIERS
    known = set(ACTIONS) | set(MODIFIERS)

    for name in ("README.md", "llms.txt", "AGENTS.md"):
        text = (ROOT / name).read_text(encoding="utf-8")
        for flag in set(re.findall(r"(?<![\w-])--[a-z][a-z-]+", text)):
            # Only flags applied to this CLI; the docs also quote npm, pip,
            # docker and mcp-publisher, which have their own vocabularies.
            if re.search(rf"oura[_-]mcp\b[^\n`]*{re.escape(flag)}", text) or \
               re.search(rf"oura-mcp\b[^\n`]*{re.escape(flag)}", text):
                assert flag in known, f"{name} cites {flag}, which the CLI rejects"


def test_both_clis_accept_the_same_flags():
    """Two implementations of one promise. A flag that works in the Python one
    and not in the TypeScript one turns the documentation into a lie for
    whichever half the person installed — and the `.mcpb` ships the TS one."""
    from oura_mcp.__main__ import ACTIONS, MODIFIERS
    ts = (ROOT / "ts" / "src" / "main.ts").read_text(encoding="utf-8")
    declared = set(re.findall(r'"(--?[a-z][a-z-]*)"', ts))
    assert set(ACTIONS) | set(MODIFIERS) == declared


def test_every_workflow_needs_a_job_that_exists():
    """A `needs:` pointing at a job that isn't there makes GitHub reject the
    WHOLE workflow, and the run fails in zero seconds with no log — which looks
    exactly like nothing happened.

    That is how v0.3.0 was tagged and not published: translating the repository
    renamed the job `pruebas` to `tests` and left `needs: pruebas` behind. The
    tag pushed, CI went green, and the publish workflow was never valid enough
    to run. Nobody was looking, because a failure with no output is easy not to
    see.

    Parsed with a regular expression rather than PyYAML: this test runs in the
    mandatory CI, and PyYAML is not a dependency of this package. Adding one so a
    coherence test can run would trade the problem for a bigger one.
    """
    workflows = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
    assert workflows, "no workflows found — did the directory move?"

    for wf in workflows:
        lines = wf.read_text(encoding="utf-8").splitlines()
        # Job keys sit at exactly two spaces of indentation under `jobs:`.
        jobs, in_jobs = set(), False
        for line in lines:
            if re.match(r"^jobs:\s*$", line):
                in_jobs = True
                continue
            if in_jobs and re.match(r"^\S", line):
                in_jobs = False
            m = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line)
            if in_jobs and m:
                jobs.add(m.group(1))

        for line in lines:
            m = re.match(r"^\s*needs:\s*(.+)$", line)
            if not m:
                continue
            raw = m.group(1).strip().strip("[]")
            for dep in (d.strip().strip("\"'") for d in raw.split(",")):
                if dep:
                    assert dep in jobs, \
                        f"{wf.name}: `needs: {dep}` but the jobs are {sorted(jobs)}"


def test_the_publish_workflow_keeps_the_name_pypi_trusts():
    """PyPI's trusted publisher matches on the workflow's FILENAME. Renaming this
    file invalidates the publisher and the upload is rejected as untrusted —
    which is what the translation did when `publicar.yml` became `publish.yml`.

    Pinning the name here means the next rename is a deliberate act with a note
    attached, not a side effect of tidying."""
    assert (ROOT / ".github" / "workflows" / "publish.yml").exists()
    header = (ROOT / ".github" / "workflows" / "publish.yml").read_text(encoding="utf-8")
    assert "workflow  publish.yml" in header, \
        "the header must document the exact filename PyPI is configured for"


def _emitted_keys() -> set[str]:
    """Every key the client can put in a response, read from the source."""
    text = (ROOT / "src" / "oura_mcp" / "client.py").read_text(encoding="utf-8")
    return set(re.findall(r'out\["([a-z_]+)"\]', text)) | {
        "data", "collection", "n", "pages"}


def test_the_docs_do_not_name_response_keys_that_no_longer_exist():
    """Eight retired Spanish key names survived the translation in README and
    llms.txt — `campos_ignorados`, `ciclo_de_paginacion`,
    `descartados_fuera_de_rango`, `respuesta_grande`. The documentation told
    people to look for keys the server had stopped emitting.

    Worse than a dead CLI flag: a flag fails loudly, while a key that never
    arrives just looks like the condition never happened. Someone waiting for
    `campos_ignorados` concludes their field names were fine.

    Pinned by name rather than inferred, because the docs legitimately quote
    Oura's own vocabulary (`next_token`, `start_date`) and a general rule would
    fire on those.

    ASSERTING IS NOT QUOTING, again. ROADMAP.md and CHANGELOG.md record these
    names precisely so nobody brings them back, and including them here made the
    test fire on the explanation of its own rule — the third time that has
    happened in this file. Only the documents that tell a reader what to expect
    are checked.
    """
    retired = ("campos_ignorados", "ciclo_de_paginacion",
               "descartados_fuera_de_rango", "respuesta_grande",
               "continuar_desde", "columnas_desiguales")
    for name in ("README.md", "llms.txt", "AGENTS.md"):
        text = (ROOT / name).read_text(encoding="utf-8")
        for key in retired:
            assert f"`{key}`" not in text, f"{name} still documents `{key}`"


def test_the_keys_the_readme_promises_are_keys_the_server_emits():
    """The other direction: the README names keys as things you will see, and
    every one has to be reachable from the code that builds a response."""
    emitted = _emitted_keys()
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    promised = {"ignored_fields", "pagination_cycle", "discarded_out_of_range",
                "large_response", "pages", "truncated", "empty", "synthetic"}
    for key in promised:
        if f"`{key}`" in readme:
            assert key in emitted, f"README promises `{key}`, which is never set"


def test_both_clients_emit_the_same_keys():
    """The `.mcpb` ships the TypeScript client and PyPI ships the Python one. A
    key present in only one makes the documentation right for half the users."""
    ts = (ROOT / "ts" / "src" / "client.ts").read_text(encoding="utf-8")
    ts_keys = set(re.findall(r'out\["([a-z_]+)"\]', ts))
    py_keys = set(re.findall(
        r'out\["([a-z_]+)"\]',
        (ROOT / "src" / "oura_mcp" / "client.py").read_text(encoding="utf-8")))
    assert py_keys == ts_keys, \
        f"only in Python: {py_keys - ts_keys}; only in TypeScript: {ts_keys - py_keys}"


def test_the_docs_name_the_parameters_the_tool_actually_takes():
    """The README's parameter table stayed in Spanish — `dia`, `inicio`, `campos`,
    `ultimo`, `formato` — long after the tool renamed them, and `llms.txt`
    asserted outright that "parameter names are in Spanish because the codebase
    is." Oscar pasted that table back at me as evidence something was wrong. It
    was, and not only where I said: his installed server was stale AND the
    documentation was wrong on its own.

    Neither earlier guard could see it. The flag test only looked at `--flags`,
    and the key test only looked at retired response keys. Parameters are a third
    vocabulary, and it had nobody watching it.

    Reads the live schema, so renaming a parameter without touching the docs
    fails here rather than in someone's terminal.
    """
    from oura_mcp.server import oura_query
    import inspect
    fn = getattr(oura_query, "fn", oura_query)
    real = set(inspect.signature(fn).parameters)

    for name in ("README.md", "llms.txt", "AGENTS.md"):
        text = (ROOT / name).read_text(encoding="utf-8")
        for dead in ("dia", "inicio", "fin", "campos", "ultimo", "formato",
                     "coleccion"):
            assert f"`{dead}`" not in text, f"{name} still documents `{dead}`"

    # And the current names must actually appear where they are explained.
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for p in real:
        assert f"`{p}`" in readme, f"README never mentions the `{p}` parameter"


def test_both_catalogs_describe_the_collections_identically():
    """The catalog is PUBLIC OUTPUT, and the two implementations disagreed on it.

    TypeScript spells its internal shape type `dateRange` and Python spells it
    `date_range`, and both leaked straight into the tool result — so the same
    server described itself two different ways depending on which one someone
    installed. Oura's own parameters are `start_date` and `start_datetime`, so
    snake_case is the side that matches the API these names describe.

    Compares the Python catalog against the names TypeScript maps to, without
    running Node: this test lives in the mandatory CI, which has Python only.
    """
    from oura_mcp.collections import COLLECTIONS

    ts = (ROOT / "ts" / "src" / "collections.ts").read_text(encoding="utf-8")
    mapped = set(re.findall(r'"(date_range|datetime_range|single|token_only)"', ts))
    python_shapes = {f for f, _ in COLLECTIONS.values()}
    assert python_shapes <= mapped, \
        f"TypeScript maps no public name for: {python_shapes - mapped}"

    # And the count and names of collections must agree.
    ts_names = set(re.findall(r"^  ([a-zA-Z0-9_]+): \{ shape:", ts, re.M))
    assert ts_names == set(COLLECTIONS), \
        f"only in Python: {set(COLLECTIONS) - ts_names}; only in TS: {ts_names - set(COLLECTIONS)}"


def test_no_tool_returns_a_key_in_spanish():
    """The catalog returned `que_trae`. The earlier key test only read
    `client.py`, so the whole server surface went unwatched — a fourth
    vocabulary after flags, response keys and parameters.
    """
    for f in ("src/oura_mcp/server.py", "ts/src/server.ts"):
        text = (ROOT / f).read_text(encoding="utf-8")
        for dead in ("que_trae", "paginas", "coleccion", "campos_ignorados",
                     "modo", "responde"):
            assert f'"{dead}"' not in text, f"{f} returns `{dead}`"
            assert f"{dead}:" not in text, f"{f} returns `{dead}`"


def test_the_readme_documents_every_warning_key():
    """Three keys were added by the audit — `synthetic`, `rate_limited`,
    `fields_split` — and llms.txt got all three while the README got none.

    llms.txt is read by models; the README is read by people deciding whether to
    install. Documenting a warning in only one of them means half the audience
    meets it for the first time in a live response.

    `data` and `columns` are excluded: they are payload, not warnings.
    """
    payload = {"data", "columns", "collection", "n", "pages", "format"}
    emitted = _emitted_keys() - payload
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    missing = [k for k in sorted(emitted) if f"`{k}`" not in readme]
    assert not missing, f"README documents no warning called: {missing}"


def test_the_headline_arithmetic_checks_out():
    """The lead claim is three numbers that have to agree with each other:
    1,231 samples, 1,000 returned without pagination, 81%.

    They're quoted in five places. Someone correcting one of them and not the
    others produces a paragraph that argues against itself — and this claim is
    the first thing a stranger reads, the one asking them to trust the rest.

    The measurement itself can't be re-run here: it needs a real account, and
    handling someone's heart rate to re-check a README isn't a trade worth
    making. What CAN be checked is that the numbers still describe each other.
    """
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "1,231" in readme and "1,000" in readme

    # Oura's page size is 1,000 records, so one page of a 1,231-sample day is
    # 81% of it. If any of the three moves, this stops holding.
    assert round(1000 / 1231 * 100) == 81
    assert "81%" in readme

    # And 1,231 must need exactly two pages, which is the other half of the claim.
    import math
    assert math.ceil(1231 / 1000) == 2
    assert "2 pages" in readme


def test_the_month_estimate_is_marked_as_one():
    """«A month is ~37,000» is extrapolation, not measurement: 1,231 × 30 is
    36,930. The tilde is doing real work and must not be tidied away, because
    every other number in that paragraph WAS measured and the reader has no way
    to tell them apart otherwise."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    if "37,000" in readme:
        i = readme.index("37,000")
        assert readme[i - 1] == "~", "an extrapolation is presented as a measurement"


def test_the_handoff_document_names_paths_that_exist():
    """AGENTS.md is the file whose entire job is to orient whoever arrives next,
    and it sent them to `herramientas/check_drift.py` and
    `.github/workflows/deriva.yml` — a directory and a workflow renamed during
    the translation. Dead commands in the one document written to be followed.

    Checks every repo-relative path it mentions.
    """
    text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    rutas = set(re.findall(r"`?((?:tools|src|tests|ts|\.github)/[\w./-]+\.(?:py|ts|yml|sh|json))`?", text))
    assert rutas, "the handoff names no paths at all — did it lose its commands?"
    for r in sorted(rutas):
        assert (ROOT / r).exists(), f"AGENTS.md points at {r}, which does not exist"
