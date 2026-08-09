"""Cliente de la API v2 de Oura. Sin dependencias: sólo biblioteca estándar.

LO ÚNICO QUE IMPORTA DE ESTE ARCHIVO ES LA PAGINACIÓN.

Oura entrega `{"data": [...], "next_token": "..."}`. Si `next_token` viene y no
lo sigues, recibes la primera página y **nada te avisa**: la respuesta es un JSON
válido, con datos reales, que se ve completo. Para `heartrate`, que muestrea cada
cinco minutos, un mes son ~8,600 puntos y la primera página trae una fracción.

No es hipotético. Revisamos siete servidores MCP de Oura publicados y **el más
completo de todos no pagina**: en su cliente, `next_token` aparece una sola vez,
en la definición del tipo. Es el mismo error que PostgREST castiga con su tope de
1,000 filas y que ya costó caro en este proyecto, tres veces.

Por eso aquí la paginación no es una opción del llamador: es el único camino.
`obtener()` no devuelve hasta que `next_token` viene vacío, o hasta toparse con
`limite_paginas` — y en ese caso lo DICE en la respuesta, en vez de callarse.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

from .colecciones import BASE, CON_FECHA, forma

TIEMPO_LIMITE = 30
LIMITE_PAGINAS = 50          # ~50k registros; más que eso es un error de uso


class ErrorOura(RuntimeError):
    """Falla al hablar con Oura. NUNCA lleva el token en el mensaje."""


def _token() -> str:
    """El PAT, de `OURA_PAT` o del archivo que apunte `OURA_PAT_FILE`.

    La variante de archivo existe porque un servidor MCP se registra en un JSON de
    configuración, y meter ahí un token lo deja en claro en un archivo que se
    respalda, se sincroniza y se comparte al pedir ayuda. Un archivo aparte con
    permisos 600 se puede rotar sin tocar la configuración y no viaja con ella.
    """
    ruta = (os.environ.get("OURA_PAT_FILE") or "").strip()
    if ruta:
        try:
            t = open(os.path.expanduser(ruta), encoding="utf-8").read().strip()
        except OSError as e:
            raise ErrorOura(f"no se pudo leer OURA_PAT_FILE: {e.strerror}") from None
        if not t:
            raise ErrorOura(f"OURA_PAT_FILE apunta a un archivo vacío: {ruta}")
        return t
    t = (os.environ.get("OURA_PAT") or "").strip()
    if not t:
        raise ErrorOura(
            "falta OURA_PAT (o OURA_PAT_FILE). Sácalo de "
            "https://cloud.ouraring.com/personal-access-tokens"
        )
    return t


def _pedir(url: str, token: str) -> dict:
    req = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=TIEMPO_LIMITE) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        # El cuerpo del error de Oura explica la causa (rango inválido, permiso
        # faltante). Se pasa recortado a 200 caracteres: un mensaje de error es
        # lo que más se copia y se pega, y no tiene por qué arrastrar más.
        detalle = ""
        try:
            detalle = ": " + e.read().decode("utf-8", "replace")[:200]
        except Exception:
            pass
        if e.code == 401:
            raise ErrorOura("Oura rechazó el token (401). ¿Expiró el PAT?") from None
        if e.code == 429:
            raise ErrorOura("Oura está limitando la tasa (429). Espera y reintenta.") from None
        raise ErrorOura(f"Oura respondió {e.code}{detalle}") from None
    except urllib.error.URLError as e:
        raise ErrorOura(f"no se pudo alcanzar Oura: {e.reason}") from None


def obtener(coleccion: str, inicio: str | None = None, fin: str | None = None,
            limite_paginas: int = LIMITE_PAGINAS) -> dict:
    """Trae una colección COMPLETA, siguiendo `next_token` hasta el final.

    Devuelve `{"coleccion", "n", "paginas", "datos", ["truncado"]}`.

    La clave `truncado` sólo aparece si se agotaron las páginas permitidas. Un
    resultado incompleto que no se declara incompleto es el peor de los dos
    mundos: se ve igual que uno completo.
    """
    f = forma(coleccion)
    token = _token()
    params: dict[str, str] = {}
    if f in CON_FECHA:
        if not inicio or not fin:
            raise ErrorOura(f"{coleccion} necesita inicio y fin")
        clave = "date" if f == "rango_fecha" else "datetime"
        params[f"start_{clave}"] = inicio
        params[f"end_{clave}"] = fin

    datos, paginas, siguiente = [], 0, None
    while True:
        q = dict(params)
        if siguiente:
            q["next_token"] = siguiente
        url = f"{BASE}/{coleccion}" + (f"?{urllib.parse.urlencode(q)}" if q else "")
        cuerpo = _pedir(url, token)
        paginas += 1
        # `personal_info` y `ring_configuration` no vienen envueltos en `data`.
        trozo = cuerpo.get("data") if isinstance(cuerpo.get("data"), list) else [cuerpo]
        datos.extend(trozo)
        siguiente = cuerpo.get("next_token")
        if not siguiente:
            break
        if paginas >= limite_paginas:
            return {"coleccion": coleccion, "n": len(datos), "paginas": paginas,
                    "truncado": (f"se detuvo en {limite_paginas} páginas y Oura ofrecía más; "
                                 f"acorta el rango de fechas"),
                    "datos": datos}
    return {"coleccion": coleccion, "n": len(datos), "paginas": paginas, "datos": datos}
