#!/usr/bin/env python3
"""Starts the server FOR REAL and speaks stdio to it, like a client would.

POR QUÉ EXISTE. Las 88 pruebas ejercitan las funciones: `fetch()`, `_token()`,
WHY IT EXISTS. The unit tests exercise functions: `fetch()`, `_token()`,
`_trim()`. None of them starts the process. And the ugliest way an MCP server
fails isn't returning wrong data: it's failing the *handshake*, or writing
something to stdout that isn't JSON-RPC. Both look identical from the client —
a server that "doesn't show up" — and no function test catches either.

It runs in sandbox mode, so it needs no credentials and can live in CI. It does
go out to the internet, so it ships with the drift check, not the mandatory CI.

    python tools/smoke_stdio.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

PROTOCOLO = "2026-07-28"


class Cliente:
    """The minimum JSON-RPC over stdio needed to talk to the server."""

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
            raise SystemExit("the server closed stdout without answering")
        try:
            return json.loads(linea)
        except json.JSONDecodeError:
            # ÉSTE es el fallo que justifica el file: cualquier `print` que se
            # slips into the server breaks the channel, and from the client all
            # you see is a server that doesn't show up.
            raise SystemExit(f"the server wrote something that is not JSON-RPC to "
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
        check("the handshake answers", "result" in r, f"server: {info.get('name')} {info.get('version')}")
        instrucciones = (r.get("result") or {}).get("instructions") or ""
        check("the instructions arrive", "truncated" in instrucciones,
                "they mention `truncated`, the thing not to ignore")

        c.pedir("notifications/initialized", {}, espera=False)

        r = c.pedir("tools/list")
        tools = (r.get("result") or {}).get("tools") or []
        nombres = sorted(h["name"] for h in tools)
        check("there are exactly three tools", len(tools) == 3, ", ".join(nombres))
        check("all three declare themselves read-only",
                all((h.get("annotations") or {}).get("readOnlyHint") for h in tools))
        check("all three have a title",
                all(h.get("title") for h in tools))

        r = c.pedir("tools/call", {"name": "oura_check", "arguments": {}})
        cuerpo = _contenido(r)
        check("oura_check answers", cuerpo.get("mode") == "sandbox",
                f"mode={cuerpo.get('mode')}, oura_responds={cuerpo.get('oura_responds')}")

        r = c.pedir("tools/call", {"name": "oura_collections", "arguments": {}})
        cuerpo = _contenido(r)
        check("the catalog carries all 19", len(cuerpo) == 19, f"{len(cuerpo)} collections")

        r = c.pedir("tools/call", {"name": "oura_query", "arguments": {
            "collection": "daily_sleep", "day": "2026-01-15"}})
        cuerpo = _contenido(r)
        check("a single-day query returns that day",
                cuerpo.get("n", 0) >= 1, f"n={cuerpo.get('n')}")

        r = c.pedir("tools/call", {"name": "oura_query", "arguments": {
            "collection": "daily_sleep", "day": "2026-01-15", "format": "csv"}})
        cuerpo = _contenido(r)
        check("the CSV arrives as text", isinstance(cuerpo.get("data"), str),
                f"columns={cuerpo.get('columns')}")

        r = c.pedir("tools/call", {"name": "oura_query", "arguments": {
            "collection": "no_existe", "day": "2026-01-15"}})
        cuerpo = _contenido(r)
        check("a made-up collection returns an error as DATA, not as an exception",
                "error" in cuerpo, "an exception would cut the whole conversation")

        # Nothing should have been written to stdout outside the protocol. If
        # anything slipped in, the request helper would already have blown up.
        check("the process is still alive", proc.poll() is None)

    finally:
        proc.terminate()
        try:
            _, err = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            err = ""
        if err.strip():
            print(f"\n  (the server's stderr, which is where it MAY write:\n   "
                  f"{err.strip()[:300]})")

    print()
    if fallas:
        print(f"{len(fallas)} failure(s): {', '.join(fallas)}")
        return 1
    print("The server starts, completes the handshake and answers over stdio.")
    return 0


def _contenido(respuesta: dict) -> dict:
    """The result of a `tools/call`, structured or as text."""
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
