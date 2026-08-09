"""Que los archivos que se repiten entre sí no se contradigan.

NO TOCAN LA RED. Sólo leen archivos del repositorio.

La versión está declarada en SEIS lugares —pyproject, server.json dos veces,
plugin.json, marketplace.json, y el `serverInfo` del handshake MCP— y se
desincronizan en silencio. Ya pasó: el servidor se anunciaba como 0.1.0 con
`pyproject.toml` en 0.2.0, y lo detectó una prueba de humo por stdio, no las 88
de función. El número que ve el cliente sale del handshake, que ninguna prueba
de función mira.

Un servidor que miente sobre su versión hace imposible diagnosticar la pregunta
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
    aquí habría hecho que la prueba de coherencia rompiera el CI justo en la
    versión más vieja que decimos soportar — que es exactamente el tipo de
    incoherencia que este archivo existe para atrapar.
    """
    texto = (RAIZ / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'^version\s*=\s*"([^"]+)"', texto, re.MULTILINE)
    assert m, "pyproject.toml sin `version`"
    return m.group(1)


# ── La versión, en todos lados ──────────────────────────────────────────────
def test_server_json_coincide_con_pyproject():
    """El registro de MCP valida que la versión exacta exista en PyPI. Si no
    coinciden, la publicación falla a medio camino: el paquete sube y el
    registro lo rechaza."""
    v = _version_declarada()
    s = _leer_json("server.json")
    assert s["version"] == v
    assert s["packages"][0]["version"] == v


def test_el_plugin_coincide_con_pyproject():
    v = _version_declarada()
    assert _leer_json(".claude-plugin/plugin.json")["version"] == v
    assert _leer_json(".claude-plugin/marketplace.json")["plugins"][0]["version"] == v


def test_el_handshake_anuncia_la_version_instalada():
    from oura_mcp.servidor import _version
    assert _version() != "desconocida"


# ── Lo que el registro exige y es fácil borrar sin querer ──────────────────
def test_el_readme_conserva_la_prueba_de_propiedad():
    """El registro de MCP comprueba que quien publica el servidor controla el
    paquete buscando esta línea en el README publicado en PyPI. Sin ella,
    `mcp-publisher publish` devuelve un 400."""
    readme = (RAIZ / "README.md").read_text(encoding="utf-8")
    nombre = _leer_json("server.json")["name"]
    assert f"mcp-name: {nombre}" in readme


def test_el_readme_trae_la_politica_de_privacidad():
    """El directorio de conectores de Claude rechaza de inmediato si falta o
    está incompleta. Tiene que cubrir seis cosas."""
    readme = (RAIZ / "README.md").read_text(encoding="utf-8")
    assert "## Privacy Policy" in readme
    for tema in ("recolecta", "guarda", "comparte", "retiene", "Contacto"):
        assert tema in readme, tema


# ── Que la documentación no se contradiga a sí misma ───────────────────────
def _docs() -> dict[str, str]:
    """Los documentos, con lo entrecomillado quitado.

    AFIRMAR NO ES CITAR. Estos archivos documentan afirmaciones que caducaron
    —«cuatro herramientas», «el más completo no pagina»— precisamente para que
    nadie las repita, y una prueba que no distinga las dos cosas se dispara con
    la explicación de su propia regla. Pasó a la primera corrida.

    Las comillas angulares son la convención de este repositorio para citar, así
    que lo que va entre ellas se descarta antes de revisar.
    """
    docs = {}
    for n in ("README.md", "AGENTS.md", "ROADMAP.md", "CHANGELOG.md", "llms.txt"):
        texto = (RAIZ / n).read_text(encoding="utf-8")
        docs[n] = re.sub(r"«[^»]*»", "«…»", texto)
    return docs


def test_el_codigo_fuente_tampoco_repite_la_frase():
    """La prueba de abajo sólo miraba los documentos, y la frase también vivía en
    el docstring de `cliente.py`. Los comentarios envejecen igual que el README y
    engañan igual — con la diferencia de que nadie los relee."""
    for f in (RAIZ / "src" / "oura_mcp").glob("*.py"):
        texto = re.sub(r"«[^»]*»", "«…»", f.read_text(encoding="utf-8"))
        assert "más completo de todos no pagina" not in texto, f.name


def test_ningun_documento_repite_la_frase_que_dejo_de_ser_cierta():
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
        assert "cuatro herramientas" not in texto.lower(), nombre


def test_el_numero_de_colecciones_es_el_mismo_en_todos_lados():
    from oura_mcp.colecciones import COLECCIONES
    assert len(COLECCIONES) == 19
    for nombre, texto in _docs().items():
        for equivocado in ("18 colecciones", "20 colecciones", "las 18 ", "las 20 "):
            assert equivocado not in texto, f"{nombre}: {equivocado}"


def test_las_mediciones_se_citan_igual_en_todos_lados():
    """1,231 muestras en 2 páginas, y 56% menos con CSV. Son números medidos; si
    uno se copia mal a otro archivo, la próxima persona no sabe cuál creer."""
    for nombre, texto in _docs().items():
        if "1,231" in texto or "1231" in texto:
            assert "2 páginas" in texto, f"{nombre} cita las muestras sin las páginas"
        # Ningún documento debe traer la estimación vieja como si fuera medida.
        assert "1,250 muestras en 2 páginas" not in texto, nombre


def test_ningun_documento_manda_a_crear_un_token_personal():
    """Oura dejó de emitirlos en diciembre de 2025. Mandar a esa página deja a
    quien llegue atorado sin saber por qué."""
    for nombre, texto in _docs().items():
        if "personal-access-tokens" in texto:
            # Sólo se permite si va acompañado de la advertencia.
            assert "diciembre de 2025" in texto, f"{nombre} manda a la página sin advertir"
