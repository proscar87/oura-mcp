"""El flujo interactivo de OAuth2: del navegador al primer par de tokens.

Corre UNA VEZ, a mano, desde la terminal. No es parte del server MCP — un
server que habla por stdin/stdout no puede abrir un navegador ni pedirle nada
a nadie, y pretender que sí es cómo se cuelga un client MCP para siempre.

    oura-mcp --authorize             # abre el navegador y espera el callback
    oura-mcp --authorize --manual    # imprime la URL; tú pegas la de vuelta

EL `state` NO ES OPCIONAL. El callback llega a un server HTTP en localhost que
acepta lo que le manden; sin un `state` que se compare, cualquier página que el
usuario tenga abierta puede mandarle un código de autorización de otra cuenta y
dejarlo conectado a data que no son suyos. Se genera con `secrets` y se
verifica antes de canjear nada.
"""

from __future__ import annotations

import http.server
import os
import secrets
import sys
import threading
import time
import urllib.parse
import webbrowser

from .client import OuraError
from .credentials import (SCOPES, AUTORIZAR_URL, DEFAULT_REDIRECT,
                           exchange_code)

CALLBACK_WAIT = 300          # cinco minutos para authorize en el navegador

_PAGINA = """<!doctype html><html lang="es"><meta charset="utf-8">
<title>oura-mcp</title>
<body style="font-family:system-ui;max-width:32rem;margin:6rem auto;line-height:1.5">
<h1>{titulo}</h1><p>{cuerpo}</p></body></html>"""


def app_credentials() -> tuple[str, str]:
    """El client_id y el client_secret de la aplicación de Oura.

    Van en el entorno y no en un file del repositorio, por lo obvio. Se
    registran una vez en https://cloud.ouraring.com/oauth/applications con el
    redirect que termina en diagonal.
    """
    cid = (os.environ.get("OURA_CLIENT_ID") or "").strip()
    csec = (os.environ.get("OURA_CLIENT_SECRET") or "").strip()
    if not cid or not csec:
        raise OuraError(
            "OURA_CLIENT_ID and OURA_CLIENT_SECRET are missing. Register an application "
            "at https://cloud.ouraring.com/oauth/applications with the redirect "
            f"{DEFAULT_REDIRECT} (the trailing slash is required)"
        )
    return cid, csec


def authorization_url(client_id: str, estado: str,
                        redirect_uri: str = DEFAULT_REDIRECT,
                        scopes: tuple[str, ...] = SCOPES) -> str:
    return AUTORIZAR_URL + "?" + urllib.parse.urlencode({
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": " ".join(scopes),
        "state": estado,
    })


def extract_code(url_o_codigo: str, estado_esperado: str | None = None) -> str:
    """Saca el `code` de la URL del callback. Verifica el `state` si se le da.

    Acepta la URL entera porque es lo que el usuario puede copiar de la barra de
    direcciones sin pensar. Si le dan sólo el código, también sirve.
    """
    texto = url_o_codigo.strip()
    # ¿Es una URL o un código pelado? Se decide por la shape, no por los
    # characters: los códigos de OAuth son base64url y traen `-`, `_` y `=` de
    # relleno con toda normalidad. La heurística anterior rechazaba `abc=` como
    # «eso no trae un code», que es de las cosas más desconcertantes que le
    # pueden pasar a alguien que pegó exactamente lo que se le pidió.
    parece_url = texto.startswith(("http://", "https://")) or "?" in texto
    if not parece_url:
        return texto
    partes = urllib.parse.urlparse(texto)
    if not partes.query:
        raise OuraError("that URL has no parameters; paste the full callback URL")
    q = urllib.parse.parse_qs(partes.query)
    if "error" in q:
        desc = (q.get("error_description") or q["error"])[0]
        raise OuraError(f"Oura rejected the authorization: {desc}")
    codigo = (q.get("code") or [""])[0]
    if not codigo:
        raise OuraError("the URL carries no `code`")
    if estado_esperado is not None:
        recibido = (q.get("state") or [""])[0]
        if not secrets.compare_digest(recibido, estado_esperado):
            raise OuraError(
                "the `state` does not match: that callback did not come from this session. "
                "Nothing was exchanged. Start over."
            )
    return codigo


class _Recolector(http.server.BaseHTTPRequestHandler):
    """Atiende UNA petición: la del callback. Nada más."""

    resultado: dict = {}

    def do_GET(self):                                   # noqa: N802
        partes = urllib.parse.urlparse(self.path)
        # El redirect registrado termina en diagonal, pero algunos navegadores
        # la quitan al normalizar. Se aceptan las dos formas.
        if partes.path.rstrip("/") != "/callback":
            self.send_error(404)
            return
        try:
            codigo = extract_code(self.path, _Recolector.resultado.get("estado"))
            _Recolector.resultado["codigo"] = codigo
            titulo, cuerpo = "Listo", "Ya puedes cerrar esta pestaña y volver a la terminal."
        except OuraError as e:
            _Recolector.resultado["error"] = str(e)
            titulo, cuerpo = "No se pudo", str(e)
        pagina = _PAGINA.format(titulo=titulo, cuerpo=cuerpo).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(pagina)))
        self.end_headers()
        self.wfile.write(pagina)

    def log_message(self, *a):
        pass                    # el server no tiene por qué ensuciar la terminal


def wait_for_callback(puerto: int, estado: str, espera: int = CALLBACK_WAIT) -> str:
    """Levanta el server local y espera EL CALLBACK, no la primera petición.

    La diferencia costó el flujo entero. Un navegador de verdad no manda una
    sola petición: pide `/favicon.ico` por su cuenta, y algunos hacen otras.
    Atendiendo sólo una, el favicon se llevaba el turno, el server se cerraba,
    y el callback bueno recibía *connection refused*. Desde afuera se veía «no
    llegó ningún callback», sin ninguna pista de por qué.

    Por eso se atiende hasta que llegue algo a `/callback` —o hasta que se acabe
    el tiempo—, no hasta la primera petición que sea.
    """
    _Recolector.resultado = {"estado": estado}
    try:
        server = http.server.HTTPServer(("127.0.0.1", puerto), _Recolector)
    except OSError as e:
        raise OuraError(
            f"could not listen on port {puerto} ({e.strerror}). "
            f"Is another authorization running? Try --manual"
        ) from None

    hilo = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.2},
                            daemon=True)
    hilo.start()
    limite = time.monotonic() + espera
    while time.monotonic() < limite:
        if _Recolector.resultado.get("codigo") or _Recolector.resultado.get("error"):
            break
        time.sleep(0.1)
    server.shutdown()
    hilo.join(5)
    server.server_close()

    if _Recolector.resultado.get("error"):
        raise OuraError(_Recolector.resultado["error"])
    codigo = _Recolector.resultado.get("codigo")
    if not codigo:
        raise OuraError(
            f"no callback arrived within {espera}s. If the machine has no "
            f"browser, use --manual"
        )
    return codigo


def _puerto_de(redirect: str) -> int:
    return urllib.parse.urlparse(redirect).port or 80


def authorize(manual: bool = False, redirect: str = DEFAULT_REDIRECT,
              salida=None) -> dict:
    """El flujo completo. Devuelve un resumen SIN tokens."""
    escribir = (salida or sys.stderr).write
    cid, csec = app_credentials()
    estado = secrets.token_urlsafe(24)
    url = authorization_url(cid, estado, redirect)

    if manual:
        # Para máquinas sin navegador. El callback a localhost fallará en el
        # navegador de la otra máquina —es lo esperado— y lo que sirve es la URL
        # que queda en la barra de direcciones.
        escribir("\nAbre esta URL en cualquier navegador:\n\n" + url + "\n\n"
                 "Al aceptar, el navegador intentará ir a localhost y fallará.\n"
                 "Eso es normal: copia la URL COMPLETA de la barra y pégala aquí.\n\n"
                 "URL del callback: ")
        pegado = sys.stdin.readline()
        codigo = extract_code(pegado, estado)
    else:
        escribir("\nAbriendo el navegador. Si no se abre, entra a:\n\n" + url + "\n\n"
                 "Esperando el callback…\n")
        try:
            webbrowser.open(url)
        except Exception:
            pass                # que no se abra no es fatal: la URL ya se imprimió
        codigo = wait_for_callback(_puerto_de(redirect), estado)

    cred = exchange_code(codigo, cid, csec, redirect)
    return {
        "authorized": True,
        "granted_scopes": list(cred.scopes),
        "expires_in_seconds": int(cred.expires_at - __import__("time").time()),
        "next_step": "ya puedes usar el server; el token se renueva solo",
    }
