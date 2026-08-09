"""Dónde viven los tokens de OAuth2, y cómo se rotan sin perder la sesión.

POR QUÉ EXISTE ESTE ARCHIVO
Oura deprecó los Personal Access Tokens en diciembre de 2025: no se pueden crear
nuevos. Quien llegue hoy a este servidor no tiene forma de conseguir uno, así
que OAuth2 dejó de ser una comodidad y pasó a ser la única puerta.

EL PELIGRO ESTÁ EN UNA SOLA LÍNEA
El refresh token de Oura es **de un solo uso**. Cuando se canjea, Oura lo
invalida y entrega uno nuevo. Entre las dos cosas hay una ventana en la que el
viejo ya no sirve y el nuevo todavía no está guardado — y si el proceso se cae
ahí, la sesión se pierde y hay que volver a autorizar desde el navegador.

Por eso `refrescar()` guarda ANTES de devolver, y guarda de forma atómica. No se
puede hacer mejor: Oura no ofrece un canje en dos fases. Lo que sí se puede es
que la ventana dure lo mínimo y que nunca quede un archivo a medio escribir.

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

from .cliente import ErrorOura, Secreto

TOKEN_URL = "https://api.ouraring.com/oauth/token"
AUTORIZAR_URL = "https://cloud.ouraring.com/oauth/authorize"
REVOCAR_URL = "https://api.ouraring.com/oauth/revoke"

# La diagonal final NO es un detalle de estilo: el portal de Oura rechaza
# `…/callback` con `invalid_redirect_uri` y acepta `…/callback/`. Lo documenta
# `crcatala` tras pelearse con ello, y aquí se usa la forma que el portal acepta.
REDIRECT_POR_DEFECTO = "http://localhost:9876/callback/"

# Los ocho alcances de la API v2.
ALCANCES = ("email", "personal", "daily", "heartrate", "workout", "tag",
            "session", "spo2")

# Margen antes de considerar caducado un access token. Un token que expira en
# tres segundos está, a efectos prácticos, expirado: la petición que se lance
# con él llegará tarde.
MARGEN_CADUCIDAD = 60

_SERVICIO_LLAVERO = "oura-mcp"
_CUENTA_LLAVERO = "credenciales"


def ruta_credenciales() -> str:
    """Dónde vive el archivo. `OURA_CREDENCIALES` lo mueve."""
    explicita = (os.environ.get("OURA_CREDENCIALES") or "").strip()
    if explicita:
        return os.path.expanduser(explicita)
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "oura-mcp", "credenciales.json")


@dataclasses.dataclass
class Credenciales:
    """Un par de tokens de OAuth2 y lo que hace falta para renovarlo."""

    acceso: Secreto
    refresco: Secreto | None
    expira_en: float                    # epoch en segundos
    alcances: tuple[str, ...] = ()

    def caducado(self, margen: float = MARGEN_CADUCIDAD) -> bool:
        return time.time() + margen >= self.expira_en

    def como_json(self) -> dict:
        return {
            "acceso": self.acceso.revelar(),
            "refresco": self.refresco.revelar() if self.refresco else None,
            "expira_en": self.expira_en,
            "alcances": list(self.alcances),
        }

    @classmethod
    def desde_json(cls, d: dict) -> Credenciales:
        return cls(
            acceso=Secreto(d["acceso"]),
            refresco=Secreto(d["refresco"]) if d.get("refresco") else None,
            expira_en=float(d.get("expira_en") or 0),
            alcances=tuple(d.get("alcances") or ()),
        )

    def __repr__(self) -> str:
        # Ni el acceso ni el refresco salen de aquí. `Secreto` ya se protege
        # solo, pero un dataclass con `repr=True` los imprimiría por su cuenta.
        cuando = "caducado" if self.caducado(0) else f"vigente {int(self.expira_en - time.time())}s"
        return (f"<Credenciales {cuando}, refresco={'sí' if self.refresco else 'no'}, "
                f"alcances={len(self.alcances)}>")


# ── Llavero, si está ────────────────────────────────────────────────────────
def _llavero():
    """El módulo `keyring` si el usuario lo tiene, o None. NUNCA una dependencia."""
    if (os.environ.get("OURA_SIN_LLAVERO") or "").strip():
        return None
    try:
        import keyring
        return keyring
    except Exception:
        # Cualquier excepción, no sólo ImportError: keyring falla al importar en
        # entornos sin backend configurado, y eso no puede tumbar el servidor.
        return None


# ── Guardar y cargar ────────────────────────────────────────────────────────
def guardar(cred: Credenciales) -> str:
    """Persiste las credenciales. Devuelve dónde quedaron ('llavero' o la ruta).

    Escribe de forma ATÓMICA. Un archivo de credenciales a medio escribir es
    peor que ninguno: el refresh token viejo ya se consumió, y lo único que
    podía salvar la sesión era el nuevo.
    """
    payload = json.dumps(cred.como_json(), ensure_ascii=False)

    kr = _llavero()
    if kr is not None:
        try:
            kr.set_password(_SERVICIO_LLAVERO, _CUENTA_LLAVERO, payload)
            return "llavero"
        except Exception:
            pass                        # cae al archivo, que siempre funciona

    ruta = ruta_credenciales()
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


def cargar() -> Credenciales | None:
    """Las credenciales guardadas, o None si no hay."""
    kr = _llavero()
    if kr is not None:
        try:
            crudo = kr.get_password(_SERVICIO_LLAVERO, _CUENTA_LLAVERO)
            if crudo:
                return Credenciales.desde_json(json.loads(crudo))
        except Exception:
            pass

    ruta = ruta_credenciales()
    try:
        with open(ruta, encoding="utf-8") as f:
            return Credenciales.desde_json(json.load(f))
    except FileNotFoundError:
        return None
    except (OSError, ValueError, KeyError) as e:
        raise ErrorOura(
            f"el archivo de credenciales no se pudo leer ({type(e).__name__}). "
            f"Bórralo y vuelve a autorizar: {ruta}"
        ) from None


def olvidar() -> None:
    """Borra las credenciales de los dos lados. No falla si no había."""
    kr = _llavero()
    if kr is not None:
        try:
            kr.delete_password(_SERVICIO_LLAVERO, _CUENTA_LLAVERO)
        except Exception:
            pass
    try:
        os.unlink(ruta_credenciales())
    except OSError:
        pass


# ── El canje, que es donde se pierde la sesión si se hace mal ───────────────
def _postear(datos: dict) -> dict:
    cuerpo = urllib.parse.urlencode(datos).encode()
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
        raise ErrorOura(f"Oura rechazó el canje ({e.code}){detalle}") from None
    except urllib.error.URLError as e:
        raise ErrorOura(f"no se pudo alcanzar Oura: {e.reason}") from None


def _de_respuesta(r: dict, alcances_previos: tuple[str, ...] = ()) -> Credenciales:
    if not r.get("access_token"):
        raise ErrorOura("Oura respondió sin `access_token`")
    # La pantalla de consentimiento devuelve los alcances CONCEDIDOS, que no
    # siempre son los pedidos ni se llaman igual. Se guarda lo que Oura dice que
    # dio, no lo que nosotros creímos pedir: el autodiagnóstico se apoya en esto.
    concedidos = tuple((r.get("scope") or "").split()) or alcances_previos
    return Credenciales(
        acceso=Secreto(r["access_token"]),
        refresco=Secreto(r["refresh_token"]) if r.get("refresh_token") else None,
        expira_en=time.time() + float(r.get("expires_in") or 3600),
        alcances=concedidos,
    )


def canjear_codigo(codigo: str, client_id: str, client_secret: str,
                   redirect_uri: str = REDIRECT_POR_DEFECTO) -> Credenciales:
    """Cambia el código de autorización por el primer par de tokens, y lo guarda."""
    cred = _de_respuesta(_postear({
        "grant_type": "authorization_code",
        "code": codigo,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "client_secret": client_secret,
    }))
    guardar(cred)
    return cred


def refrescar(cred: Credenciales, client_id: str, client_secret: str) -> Credenciales:
    """Renueva el par y lo GUARDA ANTES DE DEVOLVERLO.

    El orden es todo el punto. El refresh token de Oura es de un solo uso: en
    cuanto esta petición sale, el que teníamos queda muerto. Si el proceso se
    cayera entre la respuesta y el guardado, la sesión se perdería y habría que
    volver a autorizar desde el navegador.

    Si el canje falla, se relee lo guardado antes de dar la sesión por perdida:
    dos procesos que refrescan a la vez es un caso real —dos herramientas MCP
    llamadas en paralelo— y el que pierde la carrera vería un 400 aunque la
    sesión esté perfectamente viva, ya renovada por el otro.
    """
    if not cred.refresco:
        raise ErrorOura("no hay refresh token; hay que autorizar de nuevo")
    try:
        r = _postear({
            "grant_type": "refresh_token",
            "refresh_token": cred.refresco.revelar(),
            "client_id": client_id,
            "client_secret": client_secret,
        })
    except ErrorOura:
        otra = cargar()
        if otra and otra.refresco and not otra.caducado():
            return otra                 # alguien más ya refrescó; la sesión vive
        raise
    nueva = _de_respuesta(r, cred.alcances)
    guardar(nueva)                      # ANTES de devolver. No mover esta línea.
    return nueva
