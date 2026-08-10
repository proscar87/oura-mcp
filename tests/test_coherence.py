"""Que los archivos que se repiten entre sí no se contradigan.

NO TOCAN LA RED. Sólo leen archivos del repositorio.

La versión está declarada en SEIS lugares —pyproject, server.json dos veces,
plugin.json, marketplace.json, y el `serverInfo` del handshake MCP— y se
desincronizan en silencio. Ya pasó: el server se anunciaba como 0.1.0 con
`pyproject.toml` en 0.2.0, y lo detectó una prueba de humo por stdio, no las 88
de función. El número que ve el client sale del handshake, que ninguna prueba
de función mira.

Un server que miente sobre su versión hace imposible diagnosticar la pregunta
más común de un reporte de fallo: «¿tienes la que trae el arreglo?».
"""

import json
import pathlib
import re

RAIZ = pathlib.Path(__file__).parent.parent


def _leer_json(ruta: str) -> dict:
    return json.loads((RAIZ / ruta).read_text(encoding="utf-8"))


def _version_declarada() -> str:
    """La versión de `pyproject.toml`, leída con una expresión regular.

    `tomllib` es de Python 3.11 y este paquete declara 3.10 como mínimo. Usarlo
    aquí habría hecho que la prueba de coherence rompiera el CI justo en la
    versión más vieja que decimos soportar — que es exactamente el tipo de
    incoherencia que este file existe para atrapar.
    """
    texto = (RAIZ / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'^version\s*=\s*"([^"]+)"', texto, re.MULTILINE)
    assert m, "pyproject.toml sin `version`"
    return m.group(1)


# ── The version, everywhere ────────────────────────────────────────────────
def test_server_json_matches_pyproject():
    """El registro de MCP valida que la versión exacta exista en PyPI. Si no
    coinciden, la publicación falla a medio camino: el paquete sube y el
    registro lo rechaza."""
    v = _version_declarada()
    s = _leer_json("server.json")
    assert s["version"] == v
    assert s["packages"][0]["version"] == v


def test_the_plugin_matches_pyproject():
    v = _version_declarada()
    assert _leer_json(".claude-plugin/plugin.json")["version"] == v
    assert _leer_json(".claude-plugin/marketplace.json")["plugins"][0]["version"] == v


def test_the_handshake_announces_the_installed_version():
    from oura_mcp.server import _version
    assert _version() != "desconocida"


# ── What the registry demands and is easy to delete by accident ────────────
def test_the_readme_keeps_the_ownership_proof():
    """El registro de MCP comprueba que quien publica el server controla el
    paquete buscando esta línea en el README publicado en PyPI. Sin ella,
    `mcp-publisher publish` devuelve un 400."""
    readme = (RAIZ / "README.md").read_text(encoding="utf-8")
    nombre = _leer_json("server.json")["name"]
    assert f"mcp-name: {nombre}" in readme


def test_the_readme_carries_the_privacy_policy():
    """El directorio de conectores de Claude rechaza de inmediato si falta o
    está incompleta. Tiene que cubrir seis cosas.

    El README está en inglés —es lo que lee un desconocido y lo que lee quien
    revisa el directorio— mientras el código y los documentos internos siguen en
    español. Por eso los términos que se buscan aquí son los ingleses."""
    readme = (RAIZ / "README.md").read_text(encoding="utf-8")
    assert "## Privacy Policy" in readme
    for tema in ("What is collected", "What is stored", "shared with",
                 "retained", "Contact"):
        assert tema in readme, tema


# ── The documentation must not contradict itself ───────────────────────────
def _docs() -> dict[str, str]:
    """Los documentos, con lo entrecomillado quitado.

    AFIRMAR NO ES CITAR. Estos archivos documentan afirmaciones que caducaron
    —«cuatro tools», «el más completo no pagina»— precisamente para que
    nadie las repita, y una prueba que no distinga las dos cosas se dispara con
    la explicación de su propia regla. Pasó a la primera corrida.

    Las comillas angulares son la convención de este repositorio para citar, así
    que lo que va entre ellas se descarta antes de check.
    """
    docs = {}
    for n in ("README.md", "AGENTS.md", "ROADMAP.md", "CHANGELOG.md", "llms.txt"):
        texto = (RAIZ / n).read_text(encoding="utf-8")
        docs[n] = re.sub(r"«[^»]*»", "«…»", texto)
    return docs


def test_the_source_does_not_repeat_the_phrase_either():
    """La prueba de abajo sólo miraba los documentos, y la frase también vivía en
    el docstring de `client.py`. Los comentarios envejecen igual que el README y
    engañan igual — con la diferencia de que nadie los relee."""
    for f in (RAIZ / "src" / "oura_mcp").glob("*.py"):
        texto = re.sub(r"«[^»]*»", "«…»", f.read_text(encoding="utf-8"))
        assert "más completo de todos no pagina" not in texto, f.name


def test_no_document_repeats_the_phrase_that_stopped_being_true():
    """«El más completo de todos no pagina» era verdad y dejó de serlo:
    benngermin/oura-mcp pagina, con cursor reanudable. Una afirmación sobre la
    competencia que cualquiera puede verificar en un minuto es la más cara de
    dejar podrida."""
    for nombre, texto in _docs().items():
        assert "más completo de todos no pagina" not in texto, nombre
        assert "más completo no lo hace" not in texto, nombre


def test_ningun_documento_promete_cuatro_herramientas():
    """Son tres, y lo han sido siempre."""
    for nombre, texto in _docs().items():
        assert "cuatro tools" not in texto.lower(), nombre


def test_the_collection_count_matches_everywhere():
    from oura_mcp.collections import COLLECTIONS
    assert len(COLLECTIONS) == 19
    for nombre, texto in _docs().items():
        for equivocado in ("18 collections", "20 collections", "las 18 ", "las 20 "):
            assert equivocado not in texto, f"{nombre}: {equivocado}"


def test_the_measurements_are_quoted_the_same_everywhere():
    """1,231 muestras en 2 páginas. Es un número medido; si se copia mal a otro
    file, la próxima persona no sabe cuál creer. El README está en inglés, así
    que ahí la unidad se llama «pages»."""
    for nombre, texto in _docs().items():
        if "1,231" in texto or "1231" in texto:
            assert any(x in texto for x in ("2 pages", "two-page", "2 páginas")), \
                f"{nombre} cites the samples without the page count"
        # Ningún documento debe traer la estimación vieja como si fuera medida.
        assert "1,250 muestras en 2 páginas" not in texto, nombre


def test_the_outward_facing_files_are_in_english():
    """README y llms.txt son lo primero que ve un desconocido y lo que lee quien
    revisa el directorio de Claude. Los documentos internos siguen en español a
    propósito; mezclarlos es lo que hay que evitar."""
    readme = (RAIZ / "README.md").read_text(encoding="utf-8")
    llms = (RAIZ / "llms.txt").read_text(encoding="utf-8")
    for texto, nombre in ((readme, "README.md"), (llms, "llms.txt")):
        # Encabezados en español que se hayan quedado a medio traducir.
        for resto in ("## Instalación", "## Las tools", "## Licencia",
                      "## El problema"):
            assert resto not in texto, f"{nombre} conserva {resto}"
    assert "## License" in readme
    # Los nombres de parámetro SÍ siguen en español, y el README lo declara para
    # que nadie los tome por un error de traducción.
    assert "Parameter names are in Spanish" in readme


def test_no_document_sends_you_to_create_a_personal_token():
    """Oura dejó de emitirlos en diciembre de 2025. Mandar a esa página deja a
    quien llegue atorado sin saber por qué."""
    for nombre, texto in _docs().items():
        if "personal-access-tokens" in texto:
            # Sólo se permite si va acompañado de la advertencia.
            assert "diciembre de 2025" in texto, f"{nombre} manda a la página sin advertir"


def test_the_description_fits_the_registry():
    """El registro de MCP topa `description` en 100 characters. La v0.2.0 se
    publicó en PyPI y falló en el registro por seis characters de más — con PyPI
    ya subido, que es la mitad irreversible."""
    d = _leer_json("server.json")["description"]
    assert len(d) <= 100, f"{len(d)} characters: {d}"


def test_the_server_name_fits():
    """Mismo tope de la misma familia; más vale enterarse aquí."""
    assert len(_leer_json("server.json")["name"]) <= 200
