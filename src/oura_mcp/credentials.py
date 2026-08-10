"""Where the OAuth2 tokens live, and how they rotate without losing the session.

POR QUÉ EXISTE ESTE ARCHIVO
Oura deprecated Personal Access Tokens in December 2025: new ones can't be
created. Anyone arriving at this server today has no way to get one, so OAuth2
stopped being a convenience and became the only door.

THE DANGER IS IN A SINGLE LINE
Oura's refresh token is **single-use**. When it's exchanged, Oura invalidates it
and issues a new one. Between those two things there's a window where the old one
no longer works and the new one isn't saved yet — and if the process dies there,
the session is lost and you have to authorize from the browser again.

That's why `refresh()` saves BEFORE returning, and saves atomically. You can't
do better: Oura offers no two-phase exchange. What you can do is make the window
as short as possible and ensure a half-written file never exists.

WHERE THEY ARE STORED
A file with mode 600, and the system keychain **if it happens to be installed**.
`keyring` is not a dependency of this package and mustn't be: the empty
dependency list is what makes packaging it as a binary for Claude Desktop
viable. It's imported inside a `try`, and whoever has it gains without costing
anything to whoever doesn't.
"""

from __future__ import annotations

import dataclasses
import json
import os
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

from .client import OuraError, Secret

TOKEN_URL = "https://api.ouraring.com/oauth/token"
AUTORIZAR_URL = "https://cloud.ouraring.com/oauth/authorize"
REVOCAR_URL = "https://api.ouraring.com/oauth/revoke"

# The trailing slash is NOT a style detail: Oura's portal rejects `…/callback`
# with `invalid_redirect_uri` and accepts `…/callback/`. `crcatala` documents it
# after fighting with it, and the form the portal accepts is what's used here.
DEFAULT_REDIRECT = "http://localhost:9876/callback/"

# The eight scopes of the v2 API.
SCOPES = ("email", "personal", "daily", "heartrate", "workout", "tag",
            "session", "spo2")

# Margin before treating an access token as expired. One that expires in three
# seconds is, practically speaking, already expired: the request launched with it
# will arrive late.
EXPIRY_MARGIN = 60

_SERVICIO_LLAVERO = "oura-mcp"
_CUENTA_LLAVERO = "credenciales"


def credentials_path() -> str:
    """Where the file lives. `OURA_CREDENTIALS` moves it.

    Siempre absoluta. Una ruta relativa pelada —`OURA_CREDENTIALS=cred.json`,
    which is exactly what someone would write — left the directory as an empty
    string and blew up the save with a `FileNotFoundError: ''` that explains
    nothing. It would also have made the credentials depend on the directory
    the server was started from, which in an MCP client is not the one you
    el que uno cree.
    """
    explicita = (os.environ.get("OURA_CREDENTIALS") or "").strip()
    if explicita:
        return os.path.abspath(os.path.expanduser(explicita))
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "oura-mcp", "credenciales.json")


@dataclasses.dataclass
class Credentials:
    """A pair of OAuth2 tokens and what is needed to renew them."""

    access: Secret
    refresh_token: Secret | None
    expires_at: float                    # epoch seconds
    scopes: tuple[str, ...] = ()

    def expired(self, margen: float = EXPIRY_MARGIN) -> bool:
        return time.time() + margen >= self.expires_at

    def as_json(self) -> dict:
        return {
            "access": self.access.reveal(),
            "refresh_token": self.refresh_token.reveal() if self.refresh_token else None,
            "expires_at": self.expires_at,
            "scopes": list(self.scopes),
        }

    @classmethod
    def from_json(cls, d: dict) -> Credentials:
        return cls(
            access=Secret(d["access"]),
            refresh_token=Secret(d["refresh_token"]) if d.get("refresh_token") else None,
            expires_at=float(d.get("expires_at") or 0),
            scopes=tuple(d.get("scopes") or ()),
        )

    def __repr__(self) -> str:
        # Neither the access nor the refresh token leaves here. `Secret` already
        # protects itself, but a dataclass with `repr=True` would print them on
        # its own.
        when = "expired" if self.expired(0) else f"valid for {int(self.expires_at - time.time())}s"
        return (f"<Credentials {when}, refresh_token={'yes' if self.refresh_token else 'no'}, "
        return (f"<Credentials {when}, refresh_token={'yes' if self.refresh_token else 'no'}, "


# ── Keychain, if present ───────────────────────────────────────────────────
def _keyring():
    """The `keyring` module if the user has it, or None. NEVER a dependency."""
    if (os.environ.get("OURA_SIN_LLAVERO") or "").strip():
        return None
    try:
        import keyring
        return keyring
    except Exception:
        # Any exception, not just ImportError: keyring fails to import in
        # environments with no backend configured, and that can't take the server
        # down.
        return None


# ── Guardar y load ────────────────────────────────────────────────────────
def save(cred: Credentials) -> str:
    """Persists the credentials. Returns where they landed ('keychain' or path).

    Escribe de shape ATÓMICA. Un file de credenciales a medio escribir es
    worse than none: the old refresh token has already been consumed, and the
    new one was the only thing that could have saved the session.
    """
    payload = json.dumps(cred.as_json(), ensure_ascii=False)

    kr = _keyring()
    if kr is not None:
        try:
            kr.set_password(_SERVICIO_LLAVERO, _CUENTA_LLAVERO, payload)
            # Si antes hubo file, se borra: `load()` prefiere el llavero,
            # so that file would never be read again — a dead refresh token
            # token muerto en disco para siempre. Un secreto que nadie usa sigue
            # siendo un secreto que alguien puede leer.
            try:
                os.unlink(credentials_path())
            except OSError:
                pass
            return "keychain"
        except Exception:
            pass                        # cae al file, que siempre funciona

    ruta = credentials_path()
    os.makedirs(os.path.dirname(ruta), mode=0o700, exist_ok=True)
    fd, temporal = tempfile.mkstemp(dir=os.path.dirname(ruta), prefix=".cred-")
    try:
        os.fchmod(fd, 0o600)            # 600 BEFORE writing, not after
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
        os.replace(temporal, ruta)      # atomic within the same filesystem
    except BaseException:
        try:
            os.unlink(temporal)
        except OSError:
            pass
        raise
    return ruta


def load() -> Credentials | None:
    """Las credenciales guardadas, o None si no hay."""
    kr = _keyring()
    if kr is not None:
        try:
            crudo = kr.get_password(_SERVICIO_LLAVERO, _CUENTA_LLAVERO)
            if crudo:
                return Credentials.from_json(json.loads(crudo))
        except Exception:
            pass

    ruta = credentials_path()
    try:
        with open(ruta, encoding="utf-8") as f:
            return Credentials.from_json(json.load(f))
    except FileNotFoundError:
        return None
    except (OSError, ValueError, KeyError) as e:
        raise OuraError(
            f"the credentials file could not be read ({type(e).__name__}). "
            f"Delete it and authorize again: {ruta}"
        ) from None


def forget() -> None:
    """Erases the credentials from both places. Doesn't fail if there were none."""
    kr = _keyring()
    if kr is not None:
        try:
            kr.delete_password(_SERVICIO_LLAVERO, _CUENTA_LLAVERO)
        except Exception:
            pass
    try:
        os.unlink(credentials_path())
    except OSError:
        pass


# ── The exchange, which is where the session is lost if done wrong ──────────
def _post(data: dict) -> dict:
    cuerpo = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(
        TOKEN_URL, data=cuerpo,
        headers={"Content-Type": "application/x-www-form-urlencoded",
                 "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        # Oura contesta `{"error": "...", "error_description": "..."}`. La
        # description is the actionable part — "Invalid client_id." — and
        # burying it inside raw JSON forces whoever is already stuck to read it.
        detalle = ""
        try:
            crudo = e.read().decode("utf-8", "replace")
            cuerpo = json.loads(crudo)
            desc = cuerpo.get("error_description") or cuerpo.get("error")
            detalle = f": {desc}" if desc else f": {crudo[:200]}"
        except Exception:
            pass
        raise OuraError(f"Oura rejected the exchange ({e.code}){detalle}") from None
    except urllib.error.URLError as e:
        raise OuraError(f"no se pudo alcanzar Oura: {e.reason}") from None


def _from_response(r: dict, alcances_previos: tuple[str, ...] = ()) -> Credentials:
    if not r.get("access_token"):
        raise OuraError("Oura responded without `access_token`")
    # The consent screen returns the GRANTED scopes, which aren't always the
    # requested ones and aren't always named the same. What Oura says it gave is
    # stored, not what we believed we asked for: the self-check relies on this.
    concedidos = tuple((r.get("scope") or "").split()) or alcances_previos
    return Credentials(
        access=Secret(r["access_token"]),
        refresh_token=Secret(r["refresh_token"]) if r.get("refresh_token") else None,
        expires_at=time.time() + float(r.get("expires_in") or 3600),
        scopes=concedidos,
    )


def exchange_code(codigo: str, client_id: str, client_secret: str,
                   redirect_uri: str = DEFAULT_REDIRECT) -> Credentials:
    """Exchanges the authorization code for the first token pair, and saves it."""
    cred = _from_response(_post({
        "grant_type": "authorization_code",
        "code": codigo,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "client_secret": client_secret,
    }))
    save(cred)
    return cred


def refresh(cred: Credentials, client_id: str, client_secret: str) -> Credentials:
    """Renews the pair and SAVES IT BEFORE RETURNING IT.

    The order is the whole point. Oura's refresh token is single-use: the moment
    this request goes out, the one we held is dead. If the process died between
    the response and the save, the session would be lost and you'd have to
    authorize from the browser again.

    If the exchange fails, what's on disk is re-read before declaring the session
    lost: two processes refreshing at once is a real case — two MCP tools called
    in parallel — and the one that loses the race would see a 400 even though the
    session is perfectly alive, already renewed by the other.
    """
    if not cred.refresh_token:
        raise OuraError("no refresh token; you need to authorize again")
    try:
        r = _post({
            "grant_type": "refresh_token",
            "refresh_token": cred.refresh_token.reveal(),
            "client_id": client_id,
            "client_secret": client_secret,
        })
    except OuraError:
        otra = load()
        if otra and otra.refresh_token and not otra.expired():
            return otra                 # somebody else already refreshed; the session lives
        raise
    nueva = _from_response(r, cred.scopes)
    save(nueva)                      # BEFORE returning. Do not move this line.
    return nueva
