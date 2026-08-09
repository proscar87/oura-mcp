"""Pruebas del flujo interactivo de OAuth2. NO TOCAN LA RED.

Lo que más importa aquí es el `state`. El callback llega a un servidor HTTP en
localhost que atiende lo que le manden; sin comparar el `state`, cualquier
página abierta en el navegador del usuario puede mandarle un código de
autorización de OTRA cuenta y dejarlo conectado a datos que no son suyos, sin
que nada se vea raro.
"""

import urllib.parse

import pytest

from oura_mcp import autorizar as az
from oura_mcp.cliente import ErrorOura


# ── La URL que se le da al navegador ────────────────────────────────────────
def test_la_url_lleva_todo_lo_que_oura_pide():
    url = az.url_de_autorizacion("mi-id", "el-estado")
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert q["response_type"] == ["code"]
    assert q["client_id"] == ["mi-id"]
    assert q["state"] == ["el-estado"]
    assert q["redirect_uri"][0].endswith("/callback/")   # la diagonal es obligatoria
    assert set(q["scope"][0].split()) == set(az.ALCANCES)


def test_sin_client_id_se_dice_dónde_registrar_la_app(monkeypatch):
    monkeypatch.delenv("OURA_CLIENT_ID", raising=False)
    monkeypatch.delenv("OURA_CLIENT_SECRET", raising=False)
    with pytest.raises(ErrorOura, match="oauth/applications"):
        az.credenciales_de_app()


def test_el_error_de_la_app_recuerda_la_diagonal(monkeypatch):
    """El portal rechaza `…/callback` con invalid_redirect_uri. Que el mensaje lo
    diga ahorra la media hora que le costó a quien lo documentó."""
    monkeypatch.delenv("OURA_CLIENT_ID", raising=False)
    monkeypatch.delenv("OURA_CLIENT_SECRET", raising=False)
    with pytest.raises(ErrorOura, match="diagonal final es obligatoria"):
        az.credenciales_de_app()


# ── El `state`: lo que impide que te conecten a la cuenta de otro ───────────
def test_un_state_que_no_coincide_no_canjea_nada():
    with pytest.raises(ErrorOura, match="no salió de esta sesión"):
        az.extraer_codigo("http://localhost:9876/callback/?code=abc&state=ajeno",
                          "el-mio")


def test_un_callback_sin_state_tampoco_pasa():
    with pytest.raises(ErrorOura, match="no salió de esta sesión"):
        az.extraer_codigo("http://localhost:9876/callback/?code=abc", "el-mio")


def test_el_state_correcto_deja_pasar():
    assert az.extraer_codigo(
        "http://localhost:9876/callback/?code=abc&state=el-mio", "el-mio") == "abc"


def test_el_state_se_compara_en_tiempo_constante():
    """`secrets.compare_digest`, no `==`. Es barato y quita una clase entera de
    ataque de la mesa sin tener que razonar si aquí aplica."""
    import inspect
    assert "compare_digest" in inspect.getsource(az.extraer_codigo)


# ── Lo que el usuario pega ──────────────────────────────────────────────────
def test_acepta_la_url_completa_que_es_lo_que_uno_copia():
    assert az.extraer_codigo(
        "http://localhost:9876/callback/?code=xyz&state=s", "s") == "xyz"


def test_acepta_el_codigo_pelado():
    assert az.extraer_codigo("xyz123") == "xyz123"


def test_un_callback_de_error_se_lee_y_se_explica():
    """Oura devuelve `error` y `error_description` en el propio callback cuando
    el usuario cancela. Tratarlo como «falta code» diría lo que no es."""
    with pytest.raises(ErrorOura, match="el usuario dijo que no"):
        az.extraer_codigo(
            "http://localhost:9876/callback/?error=access_denied"
            "&error_description=el+usuario+dijo+que+no")


def test_una_url_sin_code_lo_dice():
    with pytest.raises(ErrorOura, match="no trae `code`"):
        az.extraer_codigo("http://localhost:9876/callback/?otra_cosa=1")


def test_pegar_algo_que_no_es_ni_url_ni_codigo():
    with pytest.raises(ErrorOura, match="pega la URL completa"):
        az.extraer_codigo("http://localhost:9876/callback/")


# ── El puerto ───────────────────────────────────────────────────────────────
def test_el_puerto_sale_del_redirect():
    assert az._puerto_de("http://localhost:9876/callback/") == 9876
    assert az._puerto_de("http://127.0.0.1:3000/callback/") == 3000


def test_el_puerto_ocupado_sugiere_el_modo_manual(monkeypatch):
    """Es el fallo más probable de todo el flujo: dos autorizaciones a la vez, o
    un proceso viejo que no murió."""
    def ocupado(*a, **k):
        raise OSError(48, "Address already in use")

    monkeypatch.setattr(az.http.server, "HTTPServer", ocupado)
    with pytest.raises(ErrorOura, match="--manual"):
        az.esperar_callback(9876, "s", espera=1)


# ── El modo manual, para máquinas sin navegador ─────────────────────────────
def test_el_modo_manual_no_levanta_ningun_servidor(monkeypatch, capsys):
    """En una máquina sin navegador no hay a dónde redirigir: el punto del modo
    manual es que el usuario abra la URL donde sea y pegue de vuelta."""
    import io

    monkeypatch.setenv("OURA_CLIENT_ID", "id")
    monkeypatch.setenv("OURA_CLIENT_SECRET", "sec")

    def no_deberia(*a, **k):
        raise AssertionError("el modo manual no debe abrir un puerto")

    monkeypatch.setattr(az, "esperar_callback", no_deberia)

    guardadas = {}

    def canjear_falso(codigo, cid, csec, redirect):
        guardadas["codigo"] = codigo
        from oura_mcp.credenciales import Credenciales
        from oura_mcp.cliente import Secreto
        import time
        return Credenciales(Secreto("A"), Secreto("R"), time.time() + 3600, ("daily",))

    monkeypatch.setattr(az, "canjear_codigo", canjear_falso)

    estado_visto = {}
    original = az.url_de_autorizacion

    def espiar(cid, estado, *a, **k):
        estado_visto["estado"] = estado
        return original(cid, estado, *a, **k)

    monkeypatch.setattr(az, "url_de_autorizacion", espiar)

    salida = io.StringIO()
    monkeypatch.setattr(az.sys, "stdin", io.StringIO(
        "http://localhost:9876/callback/?code=EL-CODIGO&state=REEMPLAZAR\n"))

    # El estado se genera adentro, así que hay que dejar que corra una vez para
    # conocerlo. Se reinyecta la entrada con el estado correcto.
    with pytest.raises(ErrorOura):
        az.autorizar(manual=True, salida=salida)
    bueno = estado_visto["estado"]
    monkeypatch.setattr(az, "url_de_autorizacion", lambda cid, estado, *a, **k: original(cid, bueno, *a, **k))
    monkeypatch.setattr(az.secrets, "token_urlsafe", lambda n: bueno)
    monkeypatch.setattr(az.sys, "stdin", io.StringIO(
        f"http://localhost:9876/callback/?code=EL-CODIGO&state={bueno}\n"))

    resumen = az.autorizar(manual=True, salida=salida)
    assert guardadas["codigo"] == "EL-CODIGO"
    assert resumen["autorizado"] is True
    assert resumen["alcances_concedidos"] == ["daily"]
    # Y que la URL quedó impresa, que es lo único que el usuario necesita.
    assert "cloud.ouraring.com/oauth/authorize" in salida.getvalue()


def test_el_resumen_no_lleva_tokens(monkeypatch):
    """Lo que se imprime al terminar acaba pegado en chats y en issues."""
    import io, time
    from oura_mcp.credenciales import Credenciales
    from oura_mcp.cliente import Secreto

    monkeypatch.setenv("OURA_CLIENT_ID", "id")
    monkeypatch.setenv("OURA_CLIENT_SECRET", "sec")
    monkeypatch.setattr(az, "esperar_callback", lambda *a, **k: "c")
    monkeypatch.setattr(az, "canjear_codigo", lambda *a, **k: Credenciales(
        Secreto("EL-ACCESO"), Secreto("EL-REFRESCO"), time.time() + 3600, ("daily",)))
    monkeypatch.setattr(az.webbrowser, "open", lambda u: True)

    resumen = az.autorizar(salida=io.StringIO())
    texto = repr(resumen)
    assert "EL-ACCESO" not in texto
    assert "EL-REFRESCO" not in texto
