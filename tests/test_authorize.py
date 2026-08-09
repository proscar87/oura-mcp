"""Pruebas del flujo interactivo de OAuth2. NO TOCAN LA RED.

Lo que más importa aquí es el `state`. El callback llega a un server HTTP en
localhost que atiende lo que le manden; sin comparar el `state`, cualquier
página abierta en el navegador del usuario puede mandarle un código de
autorización de OTRA cuenta y dejarlo conectado a data que no son suyos, sin
que nada se vea raro.
"""

import urllib.parse

import pytest

from oura_mcp import authorize as az
from oura_mcp.client import OuraError


# ── La URL que se le da al navegador ────────────────────────────────────────
def test_la_url_lleva_todo_lo_que_oura_pide():
    url = az.authorization_url("mi-id", "el-estado")
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert q["response_type"] == ["code"]
    assert q["client_id"] == ["mi-id"]
    assert q["state"] == ["el-estado"]
    assert q["redirect_uri"][0].endswith("/callback/")   # la diagonal es obligatoria
    assert set(q["scope"][0].split()) == set(az.SCOPES)


def test_sin_client_id_se_dice_dónde_registrar_la_app(monkeypatch):
    monkeypatch.delenv("OURA_CLIENT_ID", raising=False)
    monkeypatch.delenv("OURA_CLIENT_SECRET", raising=False)
    with pytest.raises(OuraError, match="oauth/applications"):
        az.app_credentials()


def test_el_error_de_la_app_recuerda_la_diagonal(monkeypatch):
    """El portal rechaza `…/callback` con invalid_redirect_uri. Que el mensaje lo
    diga ahorra la media hora que le costó a quien lo documentó."""
    monkeypatch.delenv("OURA_CLIENT_ID", raising=False)
    monkeypatch.delenv("OURA_CLIENT_SECRET", raising=False)
    with pytest.raises(OuraError, match="trailing slash is required"):
        az.app_credentials()


# ── El `state`: lo que impide que te conecten a la cuenta de otro ───────────
def test_un_state_que_no_coincide_no_canjea_nada():
    with pytest.raises(OuraError, match="did not come from this session"):
        az.extract_code("http://localhost:9876/callback/?code=abc&state=ajeno",
                          "el-mio")


def test_un_callback_sin_state_tampoco_pasa():
    with pytest.raises(OuraError, match="did not come from this session"):
        az.extract_code("http://localhost:9876/callback/?code=abc", "el-mio")


def test_el_state_correcto_deja_pasar():
    assert az.extract_code(
        "http://localhost:9876/callback/?code=abc&state=el-mio", "el-mio") == "abc"


def test_el_state_se_compara_en_tiempo_constante():
    """`secrets.compare_digest`, no `==`. Es barato y quita una clase entera de
    ataque de la mesa sin tener que razonar si aquí aplica."""
    import inspect
    assert "compare_digest" in inspect.getsource(az.extract_code)


# ── Lo que el usuario pega ──────────────────────────────────────────────────
def test_acepta_la_url_completa_que_es_lo_que_uno_copia():
    assert az.extract_code(
        "http://localhost:9876/callback/?code=xyz&state=s", "s") == "xyz"


def test_acepta_el_codigo_pelado():
    assert az.extract_code("xyz123") == "xyz123"


def test_un_callback_de_error_se_lee_y_se_explica():
    """Oura devuelve `error` y `error_description` en el propio callback cuando
    el usuario cancela. Tratarlo como «falta code» diría lo que no es."""
    with pytest.raises(OuraError, match="the user said no"):
        az.extract_code(
            "http://localhost:9876/callback/?error=access_denied"
            "&error_description=the+user+said+no")


def test_una_url_sin_code_lo_dice():
    with pytest.raises(OuraError, match="carries no `code`"):
        az.extract_code("http://localhost:9876/callback/?otra_cosa=1")


def test_una_url_sin_parametros_lo_dice():
    with pytest.raises(OuraError, match="has no parameters"):
        az.extract_code("http://localhost:9876/callback/")


def test_un_codigo_base64url_pelado_se_acepta():
    """Los códigos de OAuth son base64url: traen `-`, `_` y `=` de relleno con
    toda normalidad. La heurística vieja miraba si el texto tenía `=` o `/` y
    rechazaba `abc=` como «eso no trae un code» — de las cosas más
    desconcertantes que le pueden pasar a quien pegó justo lo que se le pidió."""
    for codigo in ("abc-123_XYZ", "abc=", "AQABAAIAAAA=", "a/b"):
        assert az.extract_code(codigo) == codigo


def test_el_callback_sobrevive_a_las_otras_peticiones_del_navegador():
    """UN FAVICON MATABA EL FLUJO ENTERO. Un navegador de verdad no manda una
    sola petición: pide /favicon.ico por su cuenta. Atendiendo sólo la primera,
    el favicon se llevaba el turno, el server se cerraba, y el callback bueno
    recibía connection refused. Desde afuera se veía «no llegó ningún callback»,
    sin ninguna pista."""
    import threading, time, urllib.request, urllib.error

    resultado = {}

    def esperar():
        try:
            resultado["codigo"] = az.wait_for_callback(9877, "ESTADO", espera=8)
        except OuraError as e:
            resultado["error"] = str(e)

    hilo = threading.Thread(target=esperar)
    hilo.start()
    time.sleep(0.5)
    try:
        urllib.request.urlopen("http://127.0.0.1:9877/favicon.ico", timeout=3)
    except urllib.error.HTTPError:
        pass                    # el 404 es lo esperado; lo que importa es seguir vivo
    urllib.request.urlopen(
        "http://127.0.0.1:9877/callback/?code=EL-BUENO&state=ESTADO", timeout=3)
    hilo.join(12)
    assert resultado.get("codigo") == "EL-BUENO", resultado


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
    with pytest.raises(OuraError, match="--manual"):
        az.wait_for_callback(9876, "s", espera=1)


# ── El mode manual, para máquinas sin navegador ─────────────────────────────
def test_el_modo_manual_no_levanta_ningun_servidor(monkeypatch, capsys):
    """En una máquina sin navegador no hay a dónde redirigir: el punto del mode
    manual es que el usuario abra la URL donde sea y pegue de vuelta."""
    import io

    monkeypatch.setenv("OURA_CLIENT_ID", "id")
    monkeypatch.setenv("OURA_CLIENT_SECRET", "sec")

    def no_deberia(*a, **k):
        raise AssertionError("el mode manual no debe abrir un puerto")

    monkeypatch.setattr(az, "wait_for_callback", no_deberia)

    guardadas = {}

    def canjear_falso(codigo, cid, csec, redirect):
        guardadas["codigo"] = codigo
        from oura_mcp.credentials import Credentials
        from oura_mcp.client import Secret
        import time
        return Credentials(Secret("A"), Secret("R"), time.time() + 3600, ("daily",))

    monkeypatch.setattr(az, "exchange_code", canjear_falso)

    estado_visto = {}
    original = az.authorization_url

    def espiar(cid, estado, *a, **k):
        estado_visto["estado"] = estado
        return original(cid, estado, *a, **k)

    monkeypatch.setattr(az, "authorization_url", espiar)

    salida = io.StringIO()
    monkeypatch.setattr(az.sys, "stdin", io.StringIO(
        "http://localhost:9876/callback/?code=EL-CODIGO&state=REEMPLAZAR\n"))

    # El estado se genera adentro, así que hay que dejar que corra una vez para
    # conocerlo. Se reinyecta la entrada con el estado correcto.
    with pytest.raises(OuraError):
        az.authorize(manual=True, salida=salida)
    bueno = estado_visto["estado"]
    monkeypatch.setattr(az, "authorization_url", lambda cid, estado, *a, **k: original(cid, bueno, *a, **k))
    monkeypatch.setattr(az.secrets, "token_urlsafe", lambda n: bueno)
    monkeypatch.setattr(az.sys, "stdin", io.StringIO(
        f"http://localhost:9876/callback/?code=EL-CODIGO&state={bueno}\n"))

    resumen = az.authorize(manual=True, salida=salida)
    assert guardadas["codigo"] == "EL-CODIGO"
    assert resumen["authorized"] is True
    assert resumen["granted_scopes"] == ["daily"]
    # Y que la URL quedó impresa, que es lo único que el usuario necesita.
    assert "cloud.ouraring.com/oauth/authorize" in salida.getvalue()


def test_el_resumen_no_lleva_tokens(monkeypatch):
    """Lo que se imprime al terminar acaba pegado en chats y en issues."""
    import io, time
    from oura_mcp.credentials import Credentials
    from oura_mcp.client import Secret

    monkeypatch.setenv("OURA_CLIENT_ID", "id")
    monkeypatch.setenv("OURA_CLIENT_SECRET", "sec")
    monkeypatch.setattr(az, "wait_for_callback", lambda *a, **k: "c")
    monkeypatch.setattr(az, "exchange_code", lambda *a, **k: Credentials(
        Secret("EL-ACCESO"), Secret("EL-REFRESCO"), time.time() + 3600, ("daily",)))
    monkeypatch.setattr(az.webbrowser, "open", lambda u: True)

    resumen = az.authorize(salida=io.StringIO())
    texto = repr(resumen)
    assert "EL-ACCESO" not in texto
    assert "EL-REFRESCO" not in texto
