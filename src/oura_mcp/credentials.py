"""Dónde viven los tokens de OAuth2, y cómo se rotan sin perder la sesión.

POR QUÉ EXISTE ESTE ARCHIVO
Oura deprecó los Personal Access Tokens en diciembre de 2025: no se pueden crear
nuevos. Quien llegue hoy a este server no tiene shape de conseguir uno, así
que OAuth2 dejó de ser una comodidad y pasó a ser la única puerta.

EL PELIGRO ESTÁ EN UNA SOLA LÍNEA
El refresh token de Oura es **de un solo uso**. Cuando se canjea, Oura lo
invalida y entrega uno nuevo. Entre las dos cosas hay una ventana en la que el
viejo ya no sirve y el nuevo todavía no está guardado — y si el proceso se cae
ahí, la sesión se pierde y hay que volver a authorize desde el navegador.

Por eso `refresh()` guarda ANTES de devolver, y guarda de shape atómica. No se
puede hacer mejor: Oura no ofrece un canje en dos fases. Lo que sí se puede es
que la ventana dure lo mínimo y que nunca quede un file a medio escribir.

DÓNDE SE GUARDAN
Archivo con permisos 600, y el llavero del sistema **si resulta estar
instalado**. `keyring` no es una dependencia de este paquete y no debe serlo: la
lista de dependencias vacía es lo que hace viable empaquetarlo como binario para
Claude Desktop. Se importa con `try`, y quien lo tenga sale ganando sin que le
cueste nada a quien no.
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

# La diagonal final NO es un detalle de estilo: el portal de Oura rechaza
# `…/callback` con `invalid_redirect_uri` y acepta `…/callback/`. Lo documenta
# `crcatala` tras pelearse con ello, y aquí se usa la shape que el portal acepta.
DEFAULT_REDIRECT = "http://localhost:9876/callback/"

# Los ocho scopes de la API v2.
SCOPES = ("email", "personal", "daily", "heartrate", "workout", "tag",
            "session", "spo2")

# Margen antes de considerar expired un access token. Un token que expira en
# tres segundos está, a efectos prácticos, expirado: la petición que se lance
# con él llegará tarde.
EXPIRY_MARGIN = 60

_SERVICIO_LLAVERO = "oura-mcp"
_CUENTA_LLAVERO = "credenciales"


def credentials_path() -> str:
    """Dónde vive el file. `OURA_CREDENTIALS` lo mueve.

    Siempre absoluta. Una ruta relativa pelada —`OURA_CREDENTIALS=cred.json`,
    que es exactamente lo que alguien escribiría— dejaba el directorio en cadena
    vacía y hacía tronar el guardado con un `FileNotFoundError: ''` que no
    explica nada. Y además habría hecho que las credenciales dependieran del
    directorio desde el que se arrancó el server, que en un client MCP no es
    el que uno cree.
    """
    explicita = (os.environ.get("OURA_CREDENTIALS") or "").strip()
    if explicita:
        return os.path.abspath(os.path.expanduser(explicita))
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "oura-mcp", "credenciales.json")


@dataclasses.dataclass
class Credentials:
    """Un par de tokens de OAuth2 y lo que hace falta para renovarlo."""

    access: Secret
    refresh_token: Secret | None
    expires_at: float                    # epoch en segundos
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
        # Ni el access ni el refresh_token salen de aquí. `Secret` ya se protege
        # solo, pero un dataclass con `repr=True` los imprimiría por su cuenta.
        cuando = "expired" if self.expired(0) else f"vigente {int(self.expires_at - time.time())}s"
        return (f"<Credentials {cuando}, refresh_token={'sí' if self.refresh_token else 'no'}, "
                f"scopes={len(self.scopes)}>")


# ── Llavero, si está ────────────────────────────────────────────────────────
def _keyring():
    """El módulo `keyring` si el usuario lo tiene, o None. NUNCA una dependencia."""
    if (os.environ.get("OURA_SIN_LLAVERO") or "").strip():
        return None
    try:
        import keyring
        return keyring
    except Exception:
        # Cualquier excepción, no sólo ImportError: keyring falla al importar en
        # entornos sin backend configurado, y eso no puede tumbar el server.
        return None


# ── Guardar y load ────────────────────────────────────────────────────────
def save(cred: Credentials) -> str:
    """Persiste las credenciales. Devuelve dónde quedaron ('llavero' o la ruta).

    Escribe de shape ATÓMICA. Un file de credenciales a medio escribir es
    peor que ninguno: el refresh token viejo ya se consumió, y lo único que
    podía salvar la sesión era el nuevo.
    """
    payload = json.dumps(cred.as_json(), ensure_ascii=False)

    kr = _keyring()
    if kr is not None:
        try:
            kr.set_password(_SERVICIO_LLAVERO, _CUENTA_LLAVERO, payload)
            # Si antes hubo file, se borra: `load()` prefiere el llavero,
            # así que ese file ya no se leería nunca — quedaría un refresh
            # token muerto en disco para siempre. Un secreto que nadie usa sigue
            # siendo un secreto que alguien puede leer.
            try:
                os.unlink(credentials_path())
            except OSError:
                pass
            return "llavero"
        except Exception:
            pass                        # cae al file, que siempre funciona

    ruta = credentials_path()
    os.makedirs(os.path.dirname(ruta), mode=0o700, exist_ok=True)
    fd, temporal = tempfile.mkstemp(dir=os.path.dirname(ruta), prefix=".cred-")
    try:
        os.fchmod(fd, 0o600)            # 600 ANTES de escribir, no después
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
        os.replace(temporal, ruta)      # atómico dentro del mismo sistema de archivos
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
    """Borra las credenciales de los dos lados. No falla si no había."""
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


# ── El canje, que es donde se pierde la sesión si se hace mal ───────────────
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
        # descripción es la parte accionable —«Invalid client_id.»— y enterrarla
        # dentro de un JSON crudo obliga a leerlo a quien ya está atorado.
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
    # La pantalla de consentimiento devuelve los scopes CONCEDIDOS, que no
    # siempre son los pedidos ni se llaman igual. Se guarda lo que Oura dice que
    # dio, no lo que nosotros creímos pedir: el autodiagnóstico se apoya en esto.
    concedidos = tuple((r.get("scope") or "").split()) or alcances_previos
    return Credentials(
        access=Secret(r["access_token"]),
        refresh_token=Secret(r["refresh_token"]) if r.get("refresh_token") else None,
        expires_at=time.time() + float(r.get("expires_in") or 3600),
        scopes=concedidos,
    )


def exchange_code(codigo: str, client_id: str, client_secret: str,
                   redirect_uri: str = DEFAULT_REDIRECT) -> Credentials:
    """Cambia el código de autorización por el primer par de tokens, y lo guarda."""
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
    """Renueva el par y lo GUARDA ANTES DE DEVOLVERLO.

    El orden es todo el punto. El refresh token de Oura es de un solo uso: en
    cuanto esta petición sale, el que teníamos queda muerto. Si el proceso se
    cayera entre la respuesta y el guardado, la sesión se perdería y habría que
    volver a authorize desde el navegador.

    Si el canje falla, se relee lo guardado antes de dar la sesión por perdida:
    dos procesos que refrescan a la vez es un caso real —dos tools MCP
    llamadas en paralelo— y el que pierde la carrera vería un 400 aunque la
    sesión esté perfectamente viva, ya renovada por el otro.
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
            return otra                 # alguien más ya refrescó; la sesión vive
        raise
    nueva = _from_response(r, cred.scopes)
    save(nueva)                      # ANTES de devolver. No mover esta línea.
    return nueva
