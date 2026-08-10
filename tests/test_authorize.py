"""Tests for the interactive OAuth2 flow. THEY NEVER TOUCH THE NETWORK.

What matters most here is the `state`. The callback arrives at an HTTP server on
localhost that serves whatever it is sent; without comparing the `state`, any
page open in the user's browser can hand them an authorization code from ANOTHER
account and leave them connected to data that is not theirs, with nothing looking
wrong.
"""

import urllib.parse

import pytest

from oura_mcp import authorize as az
from oura_mcp.client import OuraError


# ── The URL handed to the browser ──────────────────────────────────────────
def test_the_url_carries_everything_oura_asks_for():
    url = az.authorization_url("mi-id", "el-estado")
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert q["response_type"] == ["code"]
    assert q["client_id"] == ["mi-id"]
    assert q["state"] == ["el-estado"]
    assert q["redirect_uri"][0].endswith("/callback/")   # la diagonal es obligatoria
    assert set(q["scope"][0].split()) == set(az.SCOPES)


def test_without_client_id_it_says_where_to_register_the_app(monkeypatch):
    monkeypatch.delenv("OURA_CLIENT_ID", raising=False)
    monkeypatch.delenv("OURA_CLIENT_SECRET", raising=False)
    with pytest.raises(OuraError, match="oauth/applications"):
        az.app_credentials()


def test_the_app_error_recalls_the_trailing_slash(monkeypatch):
    """The portal rejects `…/callback` with invalid_redirect_uri. Having the message
    say so saves the half hour it cost whoever documented it."""
    monkeypatch.delenv("OURA_CLIENT_ID", raising=False)
    monkeypatch.delenv("OURA_CLIENT_SECRET", raising=False)
    with pytest.raises(OuraError, match="trailing slash is required"):
        az.app_credentials()


# ── The `state`: what stops you being connected to someone else's account ──
def test_a_mismatched_state_exchanges_nothing():
    with pytest.raises(OuraError, match="did not come from this session"):
        az.extract_code("http://localhost:9876/callback/?code=abc&state=ajeno",
                          "el-mio")


def test_a_callback_without_state_does_not_pass_either():
    with pytest.raises(OuraError, match="did not come from this session"):
        az.extract_code("http://localhost:9876/callback/?code=abc", "el-mio")


def test_the_correct_state_gets_through():
    assert az.extract_code(
        "http://localhost:9876/callback/?code=abc&state=el-mio", "el-mio") == "abc"


def test_the_state_is_compared_in_constant_time():
    """`secrets.compare_digest`, not `==`. It is cheap and takes an entire class of
    attack off the table without having to reason about whether it applies."""
    import inspect
    assert "compare_digest" in inspect.getsource(az.extract_code)


# ── What the user pastes ───────────────────────────────────────────────────
def test_accepts_the_full_url_which_is_what_one_copies():
    assert az.extract_code(
        "http://localhost:9876/callback/?code=xyz&state=s", "s") == "xyz"


def test_accepts_the_bare_code():
    assert az.extract_code("xyz123") == "xyz123"


def test_an_error_callback_is_read_and_explained():
    """Oura returns `error` and `error_description` in the callback itself when the
    user cancels. Treating it as "code is missing" would say what it is not."""
    with pytest.raises(OuraError, match="the user said no"):
        az.extract_code(
            "http://localhost:9876/callback/?error=access_denied"
            "&error_description=the+user+said+no")


def test_a_url_without_code_says_so():
    with pytest.raises(OuraError, match="carries no `code`"):
        az.extract_code("http://localhost:9876/callback/?otra_cosa=1")


def test_a_url_without_parameters_says_so():
    with pytest.raises(OuraError, match="has no parameters"):
        az.extract_code("http://localhost:9876/callback/")


def test_a_bare_base64url_code_is_accepted():
    """OAuth codes are base64url: they carry `-`, `_` and `=` padding perfectly
    normally. The old heuristic looked for `=` or `/` and rejected `abc=` as
    "that carries no code" — one of the most baffling things that can happen to
    someone who pasted exactly what they were asked for."""
    for codigo in ("abc-123_XYZ", "abc=", "AQABAAIAAAA=", "a/b"):
        assert az.extract_code(codigo) == codigo


def test_the_callback_survives_the_browsers_other_requests():
    """A FAVICON KILLED THE ENTIRE FLOW. A real browser does not send one request:
    it asks for /favicon.ico on its own. Serving only the first, the favicon took
    the turn, the server closed, and the good callback got connection refused.
    From outside it looked like "no callback arrived", with no clue at all."""
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


# ── The port ───────────────────────────────────────────────────────────────
def test_the_port_comes_from_the_redirect():
    assert az._puerto_de("http://localhost:9876/callback/") == 9876
    assert az._puerto_de("http://127.0.0.1:3000/callback/") == 3000


def test_a_busy_port_suggests_manual_mode(monkeypatch):
    """The most likely failure in the whole flow: two authorizations at once, or an
    old process that never died."""
    def ocupado(*a, **k):
        raise OSError(48, "Address already in use")

    monkeypatch.setattr(az.http.server, "HTTPServer", ocupado)
    with pytest.raises(OuraError, match="--manual"):
        az.wait_for_callback(9876, "s", espera=1)


# ── Manual mode, for machines with no browser ──────────────────────────────
def test_manual_mode_starts_no_server(monkeypatch, capsys):
    """On a machine with no browser there is nowhere to redirect: the point of
    manual mode is that the user opens the URL anywhere and pastes back."""
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

    # The state is generated inside, so it has to run once to learn it. The
    # input is then re-injected with the correct state.
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
    # And that the URL was printed, which is all the user needs.
    assert "cloud.ouraring.com/oauth/authorize" in salida.getvalue()


def test_the_summary_carries_no_tokens(monkeypatch):
    """What gets printed at the end ends up pasted into chats and issues."""
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
