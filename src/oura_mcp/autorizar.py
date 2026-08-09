"""El flujo interactivo de OAuth2: del navegador al primer par de tokens.

Corre UNA VEZ, a mano, desde la terminal. No es parte del servidor MCP — un
servidor que habla por stdin/stdout no puede abrir un navegador ni pedirle nada
a nadie, y pretender que sí es cómo se cuelga un cliente MCP para siempre.

    oura-mcp --autorizar             # abre el navegador y espera el callback
    oura-mcp --autorizar --manual    # imprime la URL; tú pegas la de vuelta

EL `state` NO ES OPCIONAL. El callback llega a un servidor HTTP en localhost que
acepta lo que le manden; sin un `state` que se compare, cualquier página que el
usuario tenga abierta puede mandarle un código de autorización de otra cuenta y
dejarlo conectado a datos que no son suyos. Se genera con `secrets` y se
verifica antes de canjear nada.
"""

from __future__ import annotations

import http.server
import os
import secrets
import sys
import threading
import urllib.parse
import webbrowser

from .cliente import ErrorOura
from .credenciales import (ALCANCES, AUTORIZAR_URL, REDIRECT_POR_DEFECTO,
                           canjear_codigo)

ESPERA_CALLBACK = 300          # cinco minutos para autorizar en el navegador

_PAGINA = """<!doctype html><html lang="es"><meta charset="utf-8">
<title>oura-mcp</title>
<body style="font-family:system-ui;max-width:32rem;margin:6rem auto;line-height:1.5">
<h1>{titulo}</h1><p>{cuerpo}</p></body></html>"""


def credenciales_de_app() -> tuple[str, str]:
    """El client_id y el client_secret de la aplicación de Oura.

    Van en el entorno y no en un archivo del repositorio, por lo obvio. Se
    registran una vez en https://cloud.ouraring.com/oauth/applications con el
    redirect que termina en diagonal.
    """
    cid = (os.environ.get("OURA_CLIENT_ID") or "").strip()
    csec = (os.environ.get("OURA_CLIENT_SECRET") or "").strip()
    if not cid or not csec:
        raise ErrorOura(
            "faltan OURA_CLIENT_ID y OURA_CLIENT_SECRET. Registra una aplicación "
            "en https://cloud.ouraring.com/oauth/applications con el redirect "
            f"{REDIRECT_POR_DEFECTO} (la diagonal final es obligatoria)"
        )
    return cid, csec


def url_de_autorizacion(client_id: str, estado: str,
                        redirect_uri: str = REDIRECT_POR_DEFECTO,
                        alcances: tuple[str, ...] = ALCANCES) -> str:
    return AUTORIZAR_URL + "?" + urllib.parse.urlencode({
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": " ".join(alcances),
        "state": estado,
    })


def extraer_codigo(url_o_codigo: str, estado_esperado: str | None = None) -> str:
    """Saca el `code` de la URL del callback. Verifica el `state` si se le da.

    Acepta la URL entera porque es lo que el usuario puede copiar de la barra de
    direcciones sin pensar. Si le dan sólo el código, también sirve.
    """
    texto = url_o_codigo.strip()
    partes = urllib.parse.urlparse(texto)
    if not partes.query:
        if "=" in texto or "/" in texto:
            raise ErrorOura("eso no trae un `code`; pega la URL completa del callback")
        return texto
    q = urllib.parse.parse_qs(partes.query)
    if "error" in q:
        desc = (q.get("error_description") or q["error"])[0]
        raise ErrorOura(f"Oura rechazó la autorización: {desc}")
    codigo = (q.get("code") or [""])[0]
    if not codigo:
        raise ErrorOura("la URL no trae `code`")
    if estado_esperado is not None:
        recibido = (q.get("state") or [""])[0]
        if not secrets.compare_digest(recibido, estado_esperado):
            raise ErrorOura(
                "el `state` no coincide: ese callback no salió de esta sesión. "
                "No se canjeó nada. Vuelve a empezar."
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
            codigo = extraer_codigo(self.path, _Recolector.resultado.get("estado"))
            _Recolector.resultado["codigo"] = codigo
            titulo, cuerpo = "Listo", "Ya puedes cerrar esta pestaña y volver a la terminal."
        except ErrorOura as e:
            _Recolector.resultado["error"] = str(e)
            titulo, cuerpo = "No se pudo", str(e)
        pagina = _PAGINA.format(titulo=titulo, cuerpo=cuerpo).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(pagina)))
        self.end_headers()
        self.wfile.write(pagina)

    def log_message(self, *a):
        pass                    # el servidor no tiene por qué ensuciar la terminal


def esperar_callback(puerto: int, estado: str, espera: int = ESPERA_CALLBACK) -> str:
    """Levanta el servidor local, espera UNA petición, devuelve el código."""
    _Recolector.resultado = {"estado": estado}
    try:
        servidor = http.server.HTTPServer(("127.0.0.1", puerto), _Recolector)
    except OSError as e:
        raise ErrorOura(
            f"no se pudo escuchar en el puerto {puerto} ({e.strerror}). "
            f"¿Hay otra autorización corriendo? Prueba con --manual"
        ) from None
    servidor.timeout = espera
    hilo = threading.Thread(target=servidor.handle_request, daemon=True)
    hilo.start()
    hilo.join(espera + 1)
    servidor.server_close()

    if _Recolector.resultado.get("error"):
        raise ErrorOura(_Recolector.resultado["error"])
    codigo = _Recolector.resultado.get("codigo")
    if not codigo:
        raise ErrorOura(
            f"no llegó ningún callback en {espera}s. Si la máquina no tiene "
            f"navegador, usa --manual"
        )
    return codigo


def _puerto_de(redirect: str) -> int:
    return urllib.parse.urlparse(redirect).port or 80


def autorizar(manual: bool = False, redirect: str = REDIRECT_POR_DEFECTO,
              salida=None) -> dict:
    """El flujo completo. Devuelve un resumen SIN tokens."""
    escribir = (salida or sys.stderr).write
    cid, csec = credenciales_de_app()
    estado = secrets.token_urlsafe(24)
    url = url_de_autorizacion(cid, estado, redirect)

    if manual:
        # Para máquinas sin navegador. El callback a localhost fallará en el
        # navegador de la otra máquina —es lo esperado— y lo que sirve es la URL
        # que queda en la barra de direcciones.
        escribir("\nAbre esta URL en cualquier navegador:\n\n" + url + "\n\n"
                 "Al aceptar, el navegador intentará ir a localhost y fallará.\n"
                 "Eso es normal: copia la URL COMPLETA de la barra y pégala aquí.\n\n"
                 "URL del callback: ")
        pegado = sys.stdin.readline()
        codigo = extraer_codigo(pegado, estado)
    else:
        escribir("\nAbriendo el navegador. Si no se abre, entra a:\n\n" + url + "\n\n"
                 "Esperando el callback…\n")
        try:
            webbrowser.open(url)
        except Exception:
            pass                # que no se abra no es fatal: la URL ya se imprimió
        codigo = esperar_callback(_puerto_de(redirect), estado)

    cred = canjear_codigo(codigo, cid, csec, redirect)
    return {
        "autorizado": True,
        "alcances_concedidos": list(cred.alcances),
        "caduca_en_segundos": int(cred.expira_en - __import__("time").time()),
        "siguiente_paso": "ya puedes usar el servidor; el token se renueva solo",
    }
