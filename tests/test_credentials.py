"""Tests for OAuth2 credential storage and rotation.

THEY NEVER TOUCH THE NETWORK. The token endpoint is replaced by a fake one.

What is tested here is not "saving a JSON": it is that the window where the old
refresh token has died and the new one is not yet saved stays as short as
possible, and that a half-written file never exists. Oura invalidates the refresh
token the moment it is exchanged; getting this wrong locks the user out of their
own account until they authorize from the browser again.
"""

import io
import json
import os
import stat
import time

import pytest

from oura_mcp import credentials as cr
from oura_mcp.client import OuraError, Secret


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """Each test gets its own file, and nobody's keychain is touched."""
    monkeypatch.setenv("OURA_CREDENTIALS", str(tmp_path / "cred.json"))
    monkeypatch.setenv("OURA_NO_KEYCHAIN", "1")
    return tmp_path


def _cred(refresh_token="R1", expires_at=None, scopes=("daily",)):
    return cr.Credentials(
        access=Secret("A1"),
        refresh_token=Secret(refresh_token) if refresh_token else None,
        expires_at=time.time() + 3600 if expires_at is None else expires_at,
        scopes=scopes,
    )


# ── Saving ─────────────────────────────────────────────────────────────────
def test_el_archivo_queda_en_600():
    path = cr.save(_cred())
    mode = stat.S_IMODE(os.stat(path).st_mode)
    assert mode == 0o600, oct(mode)


def test_the_directory_ends_up_at_700(_isolate, monkeypatch):
    monkeypatch.setenv("OURA_CREDENTIALS", str(_isolate / "hondo" / "cred.json"))
    path = cr.save(_cred())
    mode = stat.S_IMODE(os.stat(os.path.dirname(path)).st_mode)
    assert mode == 0o700, oct(mode)


def test_round_trip():
    cr.save(_cred(scopes=("daily", "heartrate")))
    leida = cr.load()
    assert leida.access.reveal() == "A1"
    assert leida.refresh_token.reveal() == "R1"
    assert leida.scopes == ("daily", "heartrate")


def test_sin_archivo_no_hay_credenciales():
    assert cr.load() is None


def test_a_corrupt_file_says_what_to_do(_isolate):
    path = _isolate / "cred.json"
    path.write_text("{no es json")
    with pytest.raises(OuraError, match="authorize again"):
        cr.load()


def test_no_debris_is_left_if_it_fails_mid_write(_isolate, monkeypatch):
    """A half-written credentials file is worse than none: the old refresh token
    has already been consumed and the new one was the only thing that could save
    the session."""
    def revienta(*a, **k):
        raise OSError("disco lleno")

    monkeypatch.setattr(cr.os, "replace", revienta)
    with pytest.raises(OSError):
        cr.save(_cred())
    sobras = [p for p in os.listdir(_isolate) if p.startswith(".cred-")]
    assert sobras == [], sobras


def test_olvidar_no_falla_si_no_habia():
    cr.forget()          # no exception
    cr.save(_cred())
    cr.forget()
    assert cr.load() is None


# ── Nothing may print the tokens ───────────────────────────────────────────
def test_the_credentials_repr_carries_no_tokens():
    """`Secret` protects itself, but a dataclass with an automatic repr would print
    them on its own."""
    c = _cred()
    assert "A1" not in repr(c)
    assert "R1" not in repr(c)
    assert "valid for" in repr(c)


def test_el_archivo_guardado_no_es_legible_por_otros(_isolate):
    """Obvious, which is why it is worth testing: the contents DO carry the tokens
    in the clear, and the only thing protecting them is the file mode."""
    path = cr.save(_cred())
    assert "R1" in open(path).read()
    assert stat.S_IMODE(os.stat(path).st_mode) & 0o077 == 0


# ── Expiry ─────────────────────────────────────────────────────────────────
def test_un_token_que_expira_en_tres_segundos_ya_esta_caducado():
    """The request launched with it will arrive late."""
    assert _cred(expires_at=time.time() + 3).expired()
    assert not _cred(expires_at=time.time() + 3600).expired()


# ── The rotation: where the session is lost if done wrong ──────────────────
def _fake_token_endpoint(monkeypatch, respuesta, registrar=None):
    def postear(data):
        if registrar is not None:
            registrar.append(data)
        if isinstance(respuesta, Exception):
            raise respuesta
        return respuesta

    monkeypatch.setattr(cr, "_post", postear)


def test_refrescar_guarda_antes_de_devolver(monkeypatch):
    """THE LINE THAT MATTERS. Oura invalidates the refresh token the moment it is
    exchanged; between the response and the save there is a window where the old
    one has died and the new one does not exist on disk. This test pins that
    window as short as possible: by the time it returns, it is already saved."""
    _fake_token_endpoint(monkeypatch, {"access_token": "A2", "refresh_token": "R2",
                                  "expires_in": 3600, "scope": "daily"})
    devuelta = cr.refresh(_cred(), "id", "secreto")
    en_disco = cr.load()
    assert devuelta.refresh_token.reveal() == "R2"
    assert en_disco.refresh_token.reveal() == "R2"      # ya estaba guardado


def test_el_refresco_manda_el_token_viejo(monkeypatch):
    enviados = []
    _fake_token_endpoint(monkeypatch, {"access_token": "A2", "refresh_token": "R2",
                                  "expires_in": 3600}, registrar=enviados)
    cr.refresh(_cred(refresh_token="R1"), "id", "secreto")
    assert enviados[0]["grant_type"] == "refresh_token"
    assert enviados[0]["refresh_token"] == "R1"


def test_si_otro_proceso_ya_refresco_la_sesion_no_se_da_por_perdida(monkeypatch):
    """Two MCP tools called in parallel is a real case. The one that loses the race
    sees a 400 even though the session is alive, already renewed by the other."""
    cr.save(cr.Credentials(access=Secret("A9"), refresh_token=Secret("R9"),
                               expires_at=time.time() + 3600, scopes=("daily",)))
    _fake_token_endpoint(monkeypatch, OuraError("Oura rejected the exchange (400)"))
    recuperada = cr.refresh(_cred(refresh_token="R1"), "id", "secreto")
    assert recuperada.access.reveal() == "A9"


def test_if_it_fails_and_nothing_is_saved_it_propagates(monkeypatch):
    _fake_token_endpoint(monkeypatch, OuraError("Oura rejected the exchange (400)"))
    with pytest.raises(OuraError, match="400"):
        cr.refresh(_cred(), "id", "secreto")


def test_without_a_refresh_token_it_says_to_authorize(monkeypatch):
    with pytest.raises(OuraError, match="authorize again"):
        cr.refresh(_cred(refresh_token=None), "id", "secreto")


def test_se_guardan_los_alcances_concedidos_no_los_pedidos(monkeypatch):
    """The consent screen returns what the user ACCEPTED, which is not always what
    was asked for. The self-check relies on this."""
    _fake_token_endpoint(monkeypatch, {"access_token": "A2", "refresh_token": "R2",
                                  "expires_in": 3600, "scope": "daily personal"})
    nueva = cr.refresh(_cred(scopes=("daily", "heartrate", "spo2")), "id", "s")
    assert nueva.scopes == ("daily", "personal")


def test_a_response_without_access_token_is_an_error(monkeypatch):
    _fake_token_endpoint(monkeypatch, {"token_type": "Bearer"})
    with pytest.raises(OuraError, match="without `access_token`"):
        cr.refresh(_cred(), "id", "secreto")


def test_canjear_codigo_tambien_guarda(monkeypatch):
    enviados = []
    _fake_token_endpoint(monkeypatch, {"access_token": "A1", "refresh_token": "R1",
                                  "expires_in": 3600}, registrar=enviados)
    cr.exchange_code("el-codigo", "id", "secreto")
    assert enviados[0]["grant_type"] == "authorization_code"
    assert enviados[0]["code"] == "el-codigo"
    assert cr.load().access.reveal() == "A1"


def test_the_default_redirect_has_a_trailing_slash():
    """Not style: Oura's portal rejects `…/callback` with `invalid_redirect_uri`
    and accepts `…/callback/`."""
    assert cr.DEFAULT_REDIRECT.endswith("/callback/")


# ── Paths someone would actually write ─────────────────────────────────────
def test_una_ruta_relativa_pelada_no_truena(tmp_path, monkeypatch):
    """`OURA_CREDENTIALS=cred.json` left the directory as an empty string and blew
    up the save with `FileNotFoundError: ''`, which explains nothing. It would
    also have made the credentials depend on the directory the server was started
    from — which in an MCP client is not the one you think."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OURA_CREDENTIALS", "cred.json")
    path = cr.save(_cred())
    assert os.path.isabs(path)
    assert cr.load().refresh_token.reveal() == "R1"


def test_la_ruta_siempre_es_absoluta(monkeypatch):
    monkeypatch.setenv("OURA_CREDENTIALS", "~/x/cred.json")
    assert os.path.isabs(cr.credentials_path())


# ── The keychain path, which nothing exercised ─────────────────────────────
# It was the least-covered code in the package and it is where someone's OAuth
# secret lives. The `_isolate` fixture sets OURA_NO_KEYCHAIN so no real keychain
# is ever touched; these tests re-enable it against a fake.
class _FakeKeyring:
    """A keychain in a dict. `falla` makes every write raise, like a machine
    with keyring installed and no backend configured."""

    def __init__(self, falla=False):
        self.store: dict[tuple[str, str], str] = {}
        self.falla = falla
        self.deleted: list[tuple[str, str]] = []

    def set_password(self, service, account, value):
        if self.falla:
            raise RuntimeError("no backend")
        self.store[(service, account)] = value

    def get_password(self, service, account):
        return self.store.get((service, account))

    def delete_password(self, service, account):
        self.deleted.append((service, account))
        self.store.pop((service, account), None)


@pytest.fixture
def keyring_falso(monkeypatch):
    kr = _FakeKeyring()
    monkeypatch.delenv("OURA_NO_KEYCHAIN", raising=False)
    monkeypatch.setattr(cr, "_keyring", lambda: kr)
    return kr


def test_the_keychain_is_preferred_and_the_file_is_removed(keyring_falso, _isolate):
    """A file left behind after a keychain save is a DEAD SECRET ON DISK.

    `load()` prefers the keychain, so that file would never be read again — and
    the refresh token inside it was already consumed. A secret nobody uses is
    still a secret somebody can read.
    """
    ruta = cr.credentials_path()
    # Put a file there first, the way a version without keychain support left it.
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        f.write("{}")

    assert cr.save(_cred(refresh_token="NUEVO")) == "keychain"
    assert not os.path.exists(ruta), "the file survived a keychain save"
    assert "NUEVO" in keyring_falso.store[(cr._KEYCHAIN_SERVICE, cr._KEYCHAIN_ACCOUNT)]


def test_it_reads_back_what_it_wrote_to_the_keychain(keyring_falso):
    cr.save(_cred(refresh_token="R-LLAVERO", scopes=("daily", "heartrate")))
    leido = cr.load()
    assert leido is not None
    assert leido.refresh_token.reveal() == "R-LLAVERO"
    assert leido.scopes == ("daily", "heartrate")


def test_a_keychain_that_refuses_falls_back_to_the_file(monkeypatch, _isolate):
    """`keyring` imports fine on machines with no backend configured and then
    raises on write. Falling back is the difference between «authorize again»
    and «it just worked»."""
    roto = _FakeKeyring(falla=True)
    monkeypatch.delenv("OURA_NO_KEYCHAIN", raising=False)
    monkeypatch.setattr(cr, "_keyring", lambda: roto)

    destino = cr.save(_cred(refresh_token="R-ARCHIVO"))
    assert destino != "keychain"
    assert os.path.exists(destino)
    assert stat.S_IMODE(os.stat(destino).st_mode) == 0o600
    assert cr.load().refresh_token.reveal() == "R-ARCHIVO"


def test_forget_clears_the_keychain_as_well_as_the_file(keyring_falso):
    """Erasing only one of the two leaves a working credential behind, which is
    the opposite of what someone asking to forget them wants."""
    cr.save(_cred())
    cr.forget()
    assert (cr._KEYCHAIN_SERVICE, cr._KEYCHAIN_ACCOUNT) in keyring_falso.deleted
    assert cr.load() is None


def test_oura_s_rejection_reaches_the_person_who_is_stuck(monkeypatch):
    """Oura answers `{"error": ..., "error_description": ...}` and the
    description is the actionable half — «Invalid client_id.» Left inside raw
    JSON it forces whoever is ALREADY stuck to parse a payload to find out what
    they typed wrong."""
    import urllib.error

    def urlopen(req, timeout=None):  # noqa: ARG001
        raise urllib.error.HTTPError(
            cr.TOKEN_URL, 400, "Bad Request", None,
            io.BytesIO(json.dumps({"error": "invalid_client",
                                   "error_description": "Invalid client_id."}).encode()))

    monkeypatch.setattr(cr.urllib.request, "urlopen", urlopen)
    with pytest.raises(OuraError) as e:
        cr._post({"grant_type": "refresh_token"})
    assert "Invalid client_id." in str(e.value)
    assert "400" in str(e.value)


def test_an_unreadable_rejection_still_says_the_status(monkeypatch):
    """An HTML error page must not turn into a traceback: the status code alone
    is still worth something."""
    import urllib.error

    def urlopen(req, timeout=None):  # noqa: ARG001
        raise urllib.error.HTTPError(cr.TOKEN_URL, 502, "Bad Gateway", None,
                                     io.BytesIO(b"<html>nginx</html>"))

    monkeypatch.setattr(cr.urllib.request, "urlopen", urlopen)
    with pytest.raises(OuraError) as e:
        cr._post({"grant_type": "refresh_token"})
    assert "502" in str(e.value)


def test_an_unreachable_oura_is_not_a_traceback(monkeypatch):
    import urllib.error

    def urlopen(req, timeout=None):  # noqa: ARG001
        raise urllib.error.URLError("nombre o servicio desconocido")

    monkeypatch.setattr(cr.urllib.request, "urlopen", urlopen)
    with pytest.raises(OuraError) as e:
        cr._post({"grant_type": "refresh_token"})
    assert "could not reach Oura" in str(e.value)
