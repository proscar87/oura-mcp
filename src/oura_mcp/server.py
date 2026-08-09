"""Servidor MCP: tres tools sobre las 19 collections de Oura.

TRES, NO DIECINUEVE. Un server con una herramienta por colección obliga al
modelo a elegir entre 19 nombres parecidos antes de saber qué contienen, y cada
una hay que documentarla por separado. Aquí la colección es un parámetro y el
catálogo se consulta cuando hace falta, no se memoriza.

NO HAY HERRAMIENTAS DE ANÁLISIS. Ni correlaciones, ni detección de anomalías, ni
comparación de periodos — que es donde otros servidores ponen su valor.

La razón: un promedio calculado aquí adentro llega al modelo como un número sin
su método. Sobre nueve años de data reales, **tres de cada cuatro cambios entre
dos mediciones consecutivas caben dentro de la oscilación normal de la propia
métrica**. Un server que entrega «tu HRV subió 12%» sin decir cuánto oscila
sola esa métrica no está informando: está fabricando una señal. Aquí se entregan
los data; el análisis va donde se pueda citar el método.
"""

from __future__ import annotations

import os
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field

from .client import OuraError, fetch
from .collections import COLLECTIONS, WITH_DATE, describe, shape

# LAS TRES SON DE SÓLO LECTURA, y no es una promesa: no hay una sola escritura
# en todo el paquete — ni un POST, ni un PUT, ni un DELETE. Declararlo evita que
# el client pida confirmación en cada llamada, y el directorio de conectores de
# Claude lo exige (`title` y `readOnlyHint` en cada herramienta).
#
# `open_world_hint` va en True porque los data vienen de un servicio externo:
# la misma llamada dos veces puede devolver distinto si el anillo sincronizó en
# medio. Decir lo contrario sería invitar a que alguien memoice la respuesta.
_SOLO_LECTURA = dict(read_only_hint=True, destructive_hint=False,
                     idempotent_hint=True, open_world_hint=True)

def _version() -> str:
    """La versión del paquete instalado, no una copia escrita a mano.

    Estaba escrita a mano y se quedó en 0.1.0 mientras `pyproject.toml` iba en
    0.2.0. Lo detectó la prueba de humo por stdio, no las 88 de función: el
    número que ve el client MCP sale del `serverInfo` del handshake, que
    ninguna prueba de función mira. Un server que miente sobre su versión hace
    imposible diagnosticar «¿tienes la que trae el arreglo?».
    """
    try:
        from importlib.metadata import version
        return version("mcp-oura")
    except Exception:
        return "desconocida"


server = MCPServer(
    name="oura",
    version=_version(),
    # LO QUE UN MODELO NO PUEDE ADIVINAR. Se comprobó simulando las preguntas
    # que un usuario hace de verdad («¿cómo dormí ayer?», «¿estoy recuperado?»,
    # «¿cómo estuvo mi pulso en el ejercicio de ayer?») y viendo qué le faltaba
    # saber para contestarlas sin inventar. Estas instrucciones viajan en cada
    # sesión, así que sólo va lo que cambia una respuesta.
    instructions=(
        "Raw data from the Oura ring, via its v2 API.\n\n"
        "FOUR THINGS THAT CHANGE THE ANSWER:\n\n"
        "1. `n: 0` does NOT mean the person didn't sleep, didn't move or didn't "
        "recover. It means Oura has no records in that range, and the most common "
        "cause is that the ring hasn't synced yet — the current day is almost "
        "always missing. When that happens the response carries `empty` with what "
        "is known. Read it before concluding anything, and say there is no data, "
        "not that it didn't happen.\n\n"
        "2. If `truncated` appears, data is MISSING: continue from "
        "`continue_from`. If `pagination_cycle` appears, Oura repeated itself and "
        "what you have may be incomplete. Neither one gets ignored.\n\n"
        "3. The range is inclusive on both ends, and `day` is the shorthand for "
        "a single one. To join a workout with the heart rate during it: request "
        "`workout`, take `start_datetime` and `end_datetime` from the one you "
        "care about, and use them verbatim as `start` and `end` of `heartrate`.\n\n"
        "4. Hay collections enormes: 30 días de `daily_activity` son 250,000 "
        "characters, y el 92% es un solo campo. Si la respuesta trae "
        "`large_response`, vuelve a pedir con `fields` limitado a lo que "
        "necesites.\n\n"
        "Este server no calcula promedios ni tendencias a propósito: entrega "
        "el dato para que el análisis se haga donde se pueda citar el método."
    ),
)


@server.tool(title="Catálogo de collections de Oura",
               annotations=ToolAnnotations(title="Catálogo de collections de Oura",
                                           **_SOLO_LECTURA))
def oura_colecciones() -> dict:
    """Las 19 collections de Oura, con qué trae cada una y qué parámetros pide.

    Úsala antes de `oura_consultar` si no estás seguro del nombre exacto.
    """
    return {n: {"shape": f, "que_trae": d} for n, (f, d) in COLLECTIONS.items()}


@server.tool(title="Query an Oura collection",
               annotations=ToolAnnotations(title="Query an Oura collection",
                                           **_SOLO_LECTURA))
def oura_consultar(
    collection: Annotated[str, Field(description="Nombre exacto. Ver `oura_colecciones`.")],
    start: Annotated[str | None, Field(description="YYYY-MM-DD, or ISO 8601 with time")] = None,
    end: Annotated[str | None, Field(description="YYYY-MM-DD, or ISO 8601 with time")] = None,
    day: Annotated[str | None, Field(
        description="Shorthand for a single day: equivalent to start=end=day.")] = None,
    fields: Annotated[list[str] | None, Field(
        description="Only these fields. Oura trims on its side, so less comes "
                    "down: use it on long heartrate ranges. `day` and `id` "
                    "always come back.")] = None,
    latest: Annotated[bool, Field(
        description="Only the most recent record. heartrate and "
                    "ring_battery_level only; it needs no range.")] = False,
    format: Annotated[str, Field(
        description="`json` (default) or `csv`. CSV for large volumes: "
                    "a month of heartrate is ~37,000 records and in JSON the "
                    "keys repeat 37,000 times.")] = "json",
) -> dict:
    """Trae una colección de Oura COMPLETA en el rango pedido.

    Sigue la paginación hasta el final: Oura entrega `next_token` y quien no lo
    persigue recibe la primera página sin que nada se lo diga. Un día de
    `heartrate` son ~1,250 muestras en 2 páginas; un mes, ~37,000.

    El rango es INCLUSIVO en los dos extremos: `start` y `end` iguales devuelven
    ese día. Oura no se comporta así —unas collections excluyen el último día y
    otras no, y `workout` va desfasada a UTC— pero eso se corrige aquí.

    Las collections de rango de fecha usan AAAA-MM-DD. `heartrate` y
    `ring_battery_level` usan ISO 8601 con hora. `personal_info` y
    `ring_configuration` no llevan rango.
    """
    if collection not in COLLECTIONS:
        return {"error": f"«{collection}» is not an Oura collection",
                "available": sorted(COLLECTIONS)}
    if day:
        # «Un solo día» es la consulta más común y la que estaba rota. Que la
        # ruta común no obligue a escribir un rango es la mitad del arreglo: la
        # otra mitad ya está en el client.
        if start or end:
            return {"error": "use `day`, or `start` and `end`, but not both"}
        start = end = day
    if shape(collection) in WITH_DATE and not latest and not (start and end):
        return {"error": f"{collection} needs `start` and `end`",
                "format": "YYYY-MM-DD" if shape(collection) == "date_range" else "ISO 8601 with time"}
    try:
        if format not in ("json", "csv"):
            return {"error": f"format «{format}» does not exist; there is `json` and `csv`"}
        return fetch(collection, start, end, fields=fields, latest=latest,
                       format=format)
    except OuraError as e:
        # Se devuelve como dato, no se lanza: una excepción corta la conversación
        # entera por lo que casi siempre es una fecha mal escrita o un token vencido.
        return {"error": str(e)}


@server.tool(title="Self-check of the Oura connection",
               annotations=ToolAnnotations(title="Self-check of the Oura connection",
                                           **_SOLO_LECTURA))
def oura_revisar() -> dict:
    """Autodiagnóstico: ¿hay token y responde Oura? Sin exponer nada.

    NO devuelve el token ni ningún valor de salud. Reporta la LONGITUD del token,
    nunca el token: los mensajes de diagnóstico son los que más se copian y se
    pegan en chats y en issues.
    """
    return check()


def _modo_de_autenticacion() -> str:
    """Con qué se está autenticando, en el mismo orden en que `_token()` decide."""
    if os.environ.get("OURA_PAT_FILE"):
        return "personal token (OURA_PAT_FILE)"
    if os.environ.get("OURA_PAT"):
        return "personal token (OURA_PAT)"
    return "OAuth2"


def _estado_de_oauth() -> dict:
    """Alcances y caducidad, SIN un solo token.

    Los scopes son la respuesta a la pregunta que más se hace cuando algo
    devuelve vacío: «¿es que no hay data, o es que no di permiso?». Oura
    contesta esa diferencia con un 403 que no siempre se distingue de un rango
    sin registros, así que tenerlos a la mano ahorra el diagnóstico equivocado.
    """
    if os.environ.get("OURA_PAT_FILE") or os.environ.get("OURA_PAT"):
        return {}
    try:
        from .credentials import SCOPES, load
        cred = load()
    except OuraError as e:
        return {"credenciales": f"unreadable: {e}"}
    if cred is None:
        return {}
    import time
    faltan = int(cred.expires_at - time.time())
    fuera = sorted(set(SCOPES) - set(cred.scopes))
    return {
        "granted_scopes": list(cred.scopes),
        "ungranted_scopes": fuera,
        "access_expires_in_seconds": faltan,
        "refreshes_itself": cred.refresh_token is not None,
    }


def check() -> dict:
    """Igual que la herramienta, pero llamable desde la línea de comandos."""
    from .client import _token, base, in_sandbox
    if in_sandbox():
        # En sandbox no hay token que check y no debe parecer que sí: quien lea
        # esta respuesta tiene que saber que los data que verá son inventados.
        out: dict = {"mode": "sandbox", "data": "synthetic, from Oura, not yours",
                     "base": base()}
        try:
            # El pulso NO puede ser `personal_info`: es la única de las 19 que el
            # sandbox no sirve. Tiene sentido —es la que devuelve correo, edad,
            # peso y estatura— pero significa que aquí hay que preguntar otra
            # cosa, o el autodiagnóstico reporta caída una API que está de pie.
            r = fetch("daily_sleep", "2026-01-01", "2026-01-03")
            out["oura_responds"] = True
            out["sample_fields"] = sorted(r["data"][0]) if r["data"] else []
        except OuraError as e:
            out["oura_responds"] = False
            out["error"] = str(e)
        out["unavailable_in_sandbox"] = ["personal_info"]
        out["next_step"] = ("drop OURA_SANDBOX and set your own credential to see "
                                 "your data")
        return out
    try:
        t = _token()
    except OuraError as e:
        return {"token_present": False, "next_step": str(e)}
    out: dict = {
        "token_present": True,
        "token_length": len(t),
        "mode": _modo_de_autenticacion(),
    }
    out.update(_estado_de_oauth())
    try:
        r = fetch("personal_info")
        out["oura_responds"] = True
        # Los NOMBRES de los fields, no sus valores: confirma que la API contesta
        # sin volcar el perfil de nadie a un log.
        out["profile_fields"] = sorted(r["data"][0]) if r["data"] else []
    except OuraError as e:
        out["oura_responds"] = False
        out["error"] = str(e)
    return out


async def main() -> None:
    await server.run_stdio_async()
