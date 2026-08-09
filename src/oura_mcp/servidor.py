"""Servidor MCP: tres herramientas sobre las 19 colecciones de Oura.

TRES, NO DIECINUEVE. Un servidor con una herramienta por colección obliga al
modelo a elegir entre 19 nombres parecidos antes de saber qué contienen, y cada
una hay que documentarla por separado. Aquí la colección es un parámetro y el
catálogo se consulta cuando hace falta, no se memoriza.

NO HAY HERRAMIENTAS DE ANÁLISIS. Ni correlaciones, ni detección de anomalías, ni
comparación de periodos — que es donde otros servidores ponen su valor.

La razón: un promedio calculado aquí adentro llega al modelo como un número sin
su método. Sobre nueve años de datos reales, **tres de cada cuatro cambios entre
dos mediciones consecutivas caben dentro de la oscilación normal de la propia
métrica**. Un servidor que entrega «tu HRV subió 12%» sin decir cuánto oscila
sola esa métrica no está informando: está fabricando una señal. Aquí se entregan
los datos; el análisis va donde se pueda citar el método.
"""

from __future__ import annotations

import os
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from .cliente import ErrorOura, obtener
from .colecciones import COLECCIONES, CON_FECHA, describir, forma

servidor = MCPServer(
    name="oura",
    version="0.1.0",
    instructions=(
        "Datos crudos del anillo Oura, vía su API v2. Las respuestas traen `n` "
        "(cuántos registros) y `paginas`. Si aparece la clave `truncado`, FALTAN "
        "datos y hay que acortar el rango — no la ignores.\n\n"
        "Este servidor no calcula promedios ni tendencias a propósito: entrega el "
        "dato para que el análisis se haga donde se pueda citar el método."
    ),
)


@servidor.tool()
def oura_colecciones() -> dict:
    """Las 19 colecciones de Oura, con qué trae cada una y qué parámetros pide.

    Úsala antes de `oura_consultar` si no estás seguro del nombre exacto.
    """
    return {n: {"forma": f, "que_trae": d} for n, (f, d) in COLECCIONES.items()}


@servidor.tool()
def oura_consultar(
    coleccion: Annotated[str, Field(description="Nombre exacto. Ver `oura_colecciones`.")],
    inicio: Annotated[str | None, Field(description="AAAA-MM-DD, o ISO 8601 con hora")] = None,
    fin: Annotated[str | None, Field(description="AAAA-MM-DD, o ISO 8601 con hora")] = None,
) -> dict:
    """Trae una colección de Oura COMPLETA en el rango pedido.

    Sigue la paginación hasta el final: Oura entrega `next_token` y quien no lo
    persigue recibe la primera página sin que nada se lo diga. Un día de
    `heartrate` son ~1,250 muestras en 2 páginas; un mes, ~37,000.

    Las colecciones de rango de fecha usan AAAA-MM-DD. `heartrate` y
    `ring_battery_level` usan ISO 8601 con hora. `personal_info` y
    `ring_configuration` no llevan rango.
    """
    if coleccion not in COLECCIONES:
        return {"error": f"«{coleccion}» no es una colección de Oura",
                "las_que_hay": sorted(COLECCIONES)}
    if forma(coleccion) in CON_FECHA and not (inicio and fin):
        return {"error": f"{coleccion} necesita `inicio` y `fin`",
                "formato": "AAAA-MM-DD" if forma(coleccion) == "rango_fecha" else "ISO 8601 con hora"}
    try:
        return obtener(coleccion, inicio, fin)
    except ErrorOura as e:
        # Se devuelve como dato, no se lanza: una excepción corta la conversación
        # entera por lo que casi siempre es una fecha mal escrita o un token vencido.
        return {"error": str(e)}


@servidor.tool()
def oura_revisar() -> dict:
    """Autodiagnóstico: ¿hay token y responde Oura? Sin exponer nada.

    NO devuelve el token ni ningún valor de salud. Reporta la LONGITUD del token,
    nunca el token: los mensajes de diagnóstico son los que más se copian y se
    pegan en chats y en issues.
    """
    return revisar()


def revisar() -> dict:
    """Igual que la herramienta, pero llamable desde la línea de comandos."""
    from .cliente import _token, base, en_sandbox
    if en_sandbox():
        # En sandbox no hay token que revisar y no debe parecer que sí: quien lea
        # esta respuesta tiene que saber que los datos que verá son inventados.
        out: dict = {"modo": "sandbox", "datos": "sintéticos, de Oura, no tuyos",
                     "base": base()}
        try:
            # El pulso NO puede ser `personal_info`: es la única de las 19 que el
            # sandbox no sirve. Tiene sentido —es la que devuelve correo, edad,
            # peso y estatura— pero significa que aquí hay que preguntar otra
            # cosa, o el autodiagnóstico reporta caída una API que está de pie.
            r = obtener("daily_sleep", "2026-01-01", "2026-01-03")
            out["oura_responde"] = True
            out["campos_de_ejemplo"] = sorted(r["datos"][0]) if r["datos"] else []
        except ErrorOura as e:
            out["oura_responde"] = False
            out["error"] = str(e)
        out["no_disponible_en_sandbox"] = ["personal_info"]
        out["siguiente_paso"] = ("quita OURA_SANDBOX y pon tu propio token para ver "
                                 "tus datos")
        return out
    try:
        t = _token()
    except ErrorOura as e:
        return {"token_presente": False, "siguiente_paso": str(e)}
    out: dict = {
        "token_presente": True,
        "token_largo": len(t),
        "origen": "OURA_PAT_FILE" if os.environ.get("OURA_PAT_FILE") else "OURA_PAT",
    }
    try:
        r = obtener("personal_info")
        out["oura_responde"] = True
        # Los NOMBRES de los campos, no sus valores: confirma que la API contesta
        # sin volcar el perfil de nadie a un log.
        out["campos_del_perfil"] = sorted(r["datos"][0]) if r["datos"] else []
    except ErrorOura as e:
        out["oura_responde"] = False
        out["error"] = str(e)
    return out


async def main() -> None:
    await servidor.run_stdio_async()
