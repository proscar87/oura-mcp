#!/usr/bin/env python3
"""Arranca el servidor DE VERDAD y le habla por stdio, como lo haría un cliente.

POR QUÉ EXISTE. Las 88 pruebas ejercitan las funciones: `obtener()`, `_token()`,
`_recortar()`. Ninguna arranca el proceso. Y el modo en que un servidor MCP
falla más feo no es devolviendo un dato equivocado: es no completando el
*handshake*, o escribiendo algo en stdout que no sea JSON-RPC. Las dos cosas se
ven igual desde el cliente —un servidor que «no aparece»— y ninguna prueba de
función las atrapa.

Corre en modo sandbox, así que no pide credenciales y puede vivir en CI. Sale a
internet, eso sí, de modo que va con la deriva y no con el CI obligatorio.

    python herramientas/humo_stdio.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

PROTOCOLO = "2026-07-28"


class Cliente:
    """Lo mínimo de JSON-RPC sobre stdio para hablar con el servidor."""

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
            raise SystemExit("el servidor cerró stdout sin responder")
        try:
            return json.loads(linea)
        except json.JSONDecodeError:
            # ÉSTE es el fallo que justifica el archivo: cualquier `print` que se
            # cuele en el servidor rompe el canal, y desde el cliente sólo se ve
            # un servidor que no aparece.
            raise SystemExit(f"el servidor escribió algo que no es JSON-RPC en "
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

    def revisar(etiqueta: str, condicion: bool, detalle: str = ""):
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
        revisar("el handshake responde", "result" in r, f"servidor: {info.get('name')} {info.get('version')}")
        instrucciones = (r.get("result") or {}).get("instructions") or ""
        revisar("las instrucciones llegan", "truncado" in instrucciones,
                "mencionan `truncado`, que es lo que no hay que ignorar")

        c.pedir("notifications/initialized", {}, espera=False)

        r = c.pedir("tools/list")
        herramientas = (r.get("result") or {}).get("tools") or []
        nombres = sorted(h["name"] for h in herramientas)
        revisar("hay exactamente tres herramientas", len(herramientas) == 3, ", ".join(nombres))
        revisar("las tres se declaran de sólo lectura",
                all((h.get("annotations") or {}).get("readOnlyHint") for h in herramientas))
        revisar("las tres tienen título",
                all(h.get("title") for h in herramientas))

        r = c.pedir("tools/call", {"name": "oura_revisar", "arguments": {}})
        cuerpo = _contenido(r)
        revisar("oura_revisar responde", cuerpo.get("modo") == "sandbox",
                f"modo={cuerpo.get('modo')}, oura_responde={cuerpo.get('oura_responde')}")

        r = c.pedir("tools/call", {"name": "oura_colecciones", "arguments": {}})
        cuerpo = _contenido(r)
        revisar("el catálogo trae las 19", len(cuerpo) == 19, f"{len(cuerpo)} colecciones")

        r = c.pedir("tools/call", {"name": "oura_consultar", "arguments": {
            "coleccion": "daily_sleep", "dia": "2026-01-15"}})
        cuerpo = _contenido(r)
        revisar("una consulta de un solo día devuelve ese día",
                cuerpo.get("n", 0) >= 1, f"n={cuerpo.get('n')}")

        r = c.pedir("tools/call", {"name": "oura_consultar", "arguments": {
            "coleccion": "daily_sleep", "dia": "2026-01-15", "formato": "csv"}})
        cuerpo = _contenido(r)
        revisar("el CSV llega como texto", isinstance(cuerpo.get("datos"), str),
                f"columnas={cuerpo.get('columnas')}")

        r = c.pedir("tools/call", {"name": "oura_consultar", "arguments": {
            "coleccion": "no_existe", "dia": "2026-01-15"}})
        cuerpo = _contenido(r)
        revisar("una colección inventada devuelve error como DATO, no como excepción",
                "error" in cuerpo, "una excepción cortaría la conversación entera")

        # Nada debe haberse escrito en stdout fuera del protocolo. Si algo se
        # coló, `Cliente.pedir` ya habría reventado arriba.
        revisar("el proceso sigue vivo", proc.poll() is None)

    finally:
        proc.terminate()
        try:
            _, err = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            err = ""
        if err.strip():
            print(f"\n  (stderr del servidor, que es donde SÍ puede escribir:\n   "
                  f"{err.strip()[:300]})")

    print()
    if fallas:
        print(f"{len(fallas)} falla(s): {', '.join(fallas)}")
        return 1
    print("El servidor arranca, completa el handshake y responde por stdio.")
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
