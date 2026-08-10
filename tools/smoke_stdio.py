#!/usr/bin/env python3
"""Arranca el server DE VERDAD y le habla por stdio, como lo haría un client.

POR QUÉ EXISTE. Las 88 pruebas ejercitan las funciones: `fetch()`, `_token()`,
`_trim()`. Ninguna arranca el proceso. Y el mode en que un server MCP
falla más feo no es devolviendo un dato equivocado: es no completando el
*handshake*, o escribiendo algo en stdout que no sea JSON-RPC. Las dos cosas se
ven igual desde el client —un server que «no aparece»— y ninguna prueba de
función las atrapa.

Corre en mode sandbox, así que no pide credenciales y puede vivir en CI. Sale a
internet, eso sí, de mode que va con la deriva y no con el CI obligatorio.

    python tools/smoke_stdio.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

PROTOCOLO = "2026-07-28"


class Cliente:
    """Lo mínimo de JSON-RPC sobre stdio para hablar con el server."""

    def __init__(self, proc: subprocess.Popen):
        self.proc = proc
        self.id = 0

    def pedir(self, metodo: str, params: dict | None = None, espera=True):
        self.id += 1
        msg = {"jsonrpc": "2.0", "method": metodo}
        if params is not None:
            msg["params"] = params
        if espera:
            msg["id"] = self.id
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()
        if not espera:
            return None
        linea = self.proc.stdout.readline()
        if not linea:
            raise SystemExit("el server cerró stdout sin responder")
        try:
            return json.loads(linea)
        except json.JSONDecodeError:
            # ÉSTE es el fallo que justifica el file: cualquier `print` que se
            # cuele en el server rompe el canal, y desde el client sólo se ve
            # un server que no aparece.
            raise SystemExit(f"el server escribió algo que no es JSON-RPC en "
                             f"stdout: {linea[:200]!r}")


def main() -> int:
    entorno = dict(os.environ, OURA_SANDBOX="1")
    for var in ("OURA_PAT", "OURA_PAT_FILE"):
        entorno.pop(var, None)

    proc = subprocess.Popen(
        [sys.executable, "-m", "oura_mcp"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, env=entorno,
        cwd=os.path.join(os.path.dirname(__file__), ".."),
    )
    c = Cliente(proc)
    fallas = []

    def check(etiqueta: str, condicion: bool, detalle: str = ""):
        print(f"  {'ok ' if condicion else 'MAL'}  {etiqueta}" + (f" — {detalle}" if detalle else ""))
        if not condicion:
            fallas.append(etiqueta)

    try:
        r = c.pedir("initialize", {
            "protocolVersion": PROTOCOLO,
            "capabilities": {},
            "clientInfo": {"name": "humo", "version": "1"},
        })
        info = (r.get("result") or {}).get("serverInfo") or {}
        check("el handshake responde", "result" in r, f"server: {info.get('name')} {info.get('version')}")
        instrucciones = (r.get("result") or {}).get("instructions") or ""
        check("las instrucciones llegan", "truncated" in instrucciones,
                "mencionan `truncated`, que es lo que no hay que ignorar")

        c.pedir("notifications/initialized", {}, espera=False)

        r = c.pedir("tools/list")
        tools = (r.get("result") or {}).get("tools") or []
        nombres = sorted(h["name"] for h in tools)
        check("hay exactamente tres tools", len(tools) == 3, ", ".join(nombres))
        check("las tres se declaran de sólo lectura",
                all((h.get("annotations") or {}).get("readOnlyHint") for h in tools))
        check("las tres tienen título",
                all(h.get("title") for h in tools))

        r = c.pedir("tools/call", {"name": "oura_check", "arguments": {}})
        cuerpo = _contenido(r)
        check("oura_check responde", cuerpo.get("mode") == "sandbox",
                f"mode={cuerpo.get('mode')}, oura_responds={cuerpo.get('oura_responds')}")

        r = c.pedir("tools/call", {"name": "oura_collections", "arguments": {}})
        cuerpo = _contenido(r)
        check("el catálogo trae las 19", len(cuerpo) == 19, f"{len(cuerpo)} collections")

        r = c.pedir("tools/call", {"name": "oura_query", "arguments": {
            "collection": "daily_sleep", "day": "2026-01-15"}})
        cuerpo = _contenido(r)
        check("una consulta de un solo día devuelve ese día",
                cuerpo.get("n", 0) >= 1, f"n={cuerpo.get('n')}")

        r = c.pedir("tools/call", {"name": "oura_query", "arguments": {
            "collection": "daily_sleep", "day": "2026-01-15", "format": "csv"}})
        cuerpo = _contenido(r)
        check("el CSV llega como texto", isinstance(cuerpo.get("data"), str),
                f"columns={cuerpo.get('columns')}")

        r = c.pedir("tools/call", {"name": "oura_query", "arguments": {
            "collection": "no_existe", "day": "2026-01-15"}})
        cuerpo = _contenido(r)
        check("una colección inventada devuelve error como DATO, no como excepción",
                "error" in cuerpo, "una excepción cortaría la conversación entera")

        # Nada debe haberse escrito en stdout fuera del protocolo. Si algo se
        # coló, `Cliente.pedir` ya habría reventado arriba.
        check("el proceso sigue vivo", proc.poll() is None)

    finally:
        proc.terminate()
        try:
            _, err = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            err = ""
        if err.strip():
            print(f"\n  (stderr del server, que es donde SÍ puede escribir:\n   "
                  f"{err.strip()[:300]})")

    print()
    if fallas:
        print(f"{len(fallas)} falla(s): {', '.join(fallas)}")
        return 1
    print("El server arranca, completa el handshake y responde por stdio.")
    return 0


def _contenido(respuesta: dict) -> dict:
    """El resultado de un `tools/call`, ya sea estructurado o como texto."""
    res = respuesta.get("result") or {}
    if "structuredContent" in res:
        return res["structuredContent"]
    for item in res.get("content") or []:
        if item.get("type") == "text":
            try:
                return json.loads(item["text"])
            except json.JSONDecodeError:
                return {"texto": item["text"]}
    return {}


if __name__ == "__main__":
    sys.exit(main())
