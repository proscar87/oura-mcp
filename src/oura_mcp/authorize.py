"""The interactive OAuth2 flow: from the browser to the first token pair.

Runs ONCE, by hand, from the terminal. It is not part of the MCP server — one
that speaks over stdin/stdout can't open a browser or ask anyone anything, and
pretending otherwise is how you hang an MCP client forever.

    oura-mcp --authorize             # opens the browser, waits for the callback
    oura-mcp --authorize --manual    # prints the URL; you paste the reply

THE `state` IS NOT OPTIONAL. The callback arrives at an HTTP server on localhost
that accepts whatever it's sent; without a `state` to compare, any page the user
has open can hand them an authorization code from another account and leave them
connected to data that isn't theirs. It's generated with `secrets` and verified
before anything is exchanged.
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

CALLBACK_WAIT = 300          # five minutes to authorize in the browser

_PAGINA = """<!doctype html><html lang="es"><meta charset="utf-8">
<title>oura-mcp</title>
<body style="font-family:system-ui;max-width:32rem;margin:6rem auto;line-height:1.5">
<h1>{title}</h1><p>{body}</p></body></html>"""


def app_credentials() -> tuple[str, str]:
    """The client_id and client_secret of the Oura application.

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
    """Extracts the `code` from the callback URL. Verifies the `state` when given.

    It accepts the whole URL because that's what a user can copy from the address
    bar without thinking. A bare code works too.
    """
    texto = url_o_codigo.strip()
    # Is it a URL or a bare code? Decided by SHAPE, not by characters: OAuth
    # codes are base64url and carry `-`, `_` and `=` padding perfectly normally.
    # The earlier heuristic rejected `abc=` as "that carries no code", one of
    # the most baffling things that can happen to someone who pasted exactly
    # what they were asked for.
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
    """Serves ONE request: the callback. Nothing else."""

    resultado: dict = {}

    def do_GET(self):                                   # noqa: N802
        partes = urllib.parse.urlparse(self.path)
        # The registered redirect ends in a slash, but some browsers strip it
        # when normalising. Both forms are accepted.
        if partes.path.rstrip("/") != "/callback":
            self.send_error(404)
            return
        try:
            codigo = extract_code(self.path, _Recolector.resultado.get("estado"))
            _Recolector.resultado["codigo"] = codigo
            title, body = "Done", "You can close this tab and go back to the terminal."
        except OuraError as e:
            _Recolector.resultado["error"] = str(e)
            title, body = "It did not work", str(e)
        page = _PAGINA.format(title=title, body=body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(page)))
        self.end_headers()
        self.wfile.write(page)

    def log_message(self, *a):
        pass                    # the server has no business cluttering the terminal


def wait_for_callback(puerto: int, estado: str, espera: int = CALLBACK_WAIT) -> str:
    """Starts the local server and waits for THE CALLBACK, not the first request.

    The difference cost the entire flow. A real browser doesn't send one
    request: it asks for `/favicon.ico` on its own, and some make others. Serving
    only one, the favicon took the turn, the server closed, and the good callback
    got *connection refused*. From outside it looked like "no callback arrived",
    with no clue why.

    So it serves until something reaches `/callback` — or until time runs out —
    not until whatever the first request happens to be.
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
    """The full flow. Returns a summary with NO tokens."""
    escribir = (salida or sys.stderr).write
    cid, csec = app_credentials()
    estado = secrets.token_urlsafe(24)
    url = authorization_url(cid, estado, redirect)

    if manual:
        # For machines with no browser. The localhost callback will fail in the
        # other machine's browser — that's expected — and what's useful is the
        # URL left in the address bar.
        escribir("\nOpen this URL in any browser:\n\n" + url + "\n\n"
                 "On approval the browser will try to reach localhost and fail.\n"
                 "That is normal: copy the FULL URL from the bar and paste it here.\n\n"
                 "Callback URL: ")
        pasted = sys.stdin.readline()
        codigo = extract_code(pasted, estado)
    else:
        escribir("\nOpening the browser. If it does not open, go to:\n\n" + url + "\n\n"
                 "Waiting for the callback…\n")
        try:
            webbrowser.open(url)
        except Exception:
            pass                # failing to open isn't fatal: the URL was already printed
        codigo = wait_for_callback(_puerto_de(redirect), estado)

    cred = exchange_code(codigo, cid, csec, redirect)
    return {
        "authorized": True,
        "granted_scopes": list(cred.scopes),
        "expires_in_seconds": int(cred.expires_at - __import__("time").time()),
        "next_step": "ya puedes usar el server; el token se renueva solo",
    }
