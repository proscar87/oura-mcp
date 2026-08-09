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

import datetime
import json
import os
import urllib.error
import urllib.parse
import urllib.request

from .colecciones import BASE, CON_FECHA, forma

TIEMPO_LIMITE = 30
LIMITE_PAGINAS = 50          # ~50k registros; más que eso es un error de uso

# Días de más que se piden de cada lado antes de recortar. DOS, no uno:
# `workout` es exclusiva en el extremo Y va desfasada a UTC, y las dos cosas se
# suman. El desfase horario máximo del mundo es de ±14 h —un día— y la
# exclusividad cuesta otro. Con dos, cualquier zona horaria queda cubierta.
MARGEN_DIAS = 2

# Claves de las que se puede sacar el día de un registro, en orden de confianza.
# `day` la traen casi todas; `start_day` es de rest_mode_period y enhanced_tag;
# las de hora se recortan a diez caracteres.
_CLAVES_DIA = ("day", "start_day")
_CLAVES_HORA = ("timestamp", "start_time", "bedtime_start")


class ErrorOura(RuntimeError):
    """Falla al hablar con Oura. NUNCA lleva el token en el mensaje."""


def en_sandbox() -> bool:
    """¿Está puesto `OURA_SANDBOX`? Cualquier valor menos vacío, `0`, `no`."""
    v = (os.environ.get("OURA_SANDBOX") or "").strip().lower()
    return bool(v) and v not in ("0", "no", "false")


def base() -> str:
    """A dónde se pide. Sandbox, override explícito, o Oura de verdad.

    EL SANDBOX ES OFICIAL, no un truco: está en el OpenAPI de Oura con 34 rutas
    espejo, y acepta CUALQUIER cadena como `Authorization`. Eso permite instalar
    el servidor, verlo funcionar y entender la forma de los datos ANTES de pelear
    con la autenticación — que desde que Oura deprecó los tokens personales en
    diciembre de 2025 dejó de ser un trámite de un minuto.

    Lo que el sandbox NO sirve es para medir el comportamiento de la API: es un
    GENERADOR, no un filtro. Devuelve n-1 registros para cualquier ventana y cero
    para una de una hora que contiene una muestra. Medir la semántica de las
    fechas ahí da respuestas equivocadas — ya pasó una vez.
    """
    override = (os.environ.get("OURA_API_BASE_URL") or "").strip()
    if override:
        return override.rstrip("/")
    if en_sandbox():
        return BASE.replace("/v2/usercollection", "/v2/sandbox/usercollection")
    return BASE


def _token() -> str:
    """El PAT, de `OURA_PAT` o del archivo que apunte `OURA_PAT_FILE`.

    La variante de archivo existe porque un servidor MCP se registra en un JSON de
    configuración, y meter ahí un token lo deja en claro en un archivo que se
    respalda, se sincroniza y se comparte al pedir ayuda. Un archivo aparte con
    permisos 600 se puede rotar sin tocar la configuración y no viaja con ella.
    """
    if en_sandbox():
        # El sandbox acepta cualquier cadena. Pedir un token aquí sería inventar
        # un requisito que la API no tiene, y con él se pierde justo a quien
        # todavía no tiene cómo conseguirlo.
        return "sandbox"
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


def dia_de(registro: dict) -> str | None:
    """El día al que pertenece un registro, o None si no se puede saber.

    None significa «no sé», y quien filtra tiene que CONSERVARLO. Descartar lo
    que no se entiende es la manera más rápida de entregar de menos.
    """
    if not isinstance(registro, dict):
        return None
    for k in _CLAVES_DIA:
        v = registro.get(k)
        if isinstance(v, str) and v:
            return v[:10]
    for k in _CLAVES_HORA:
        v = registro.get(k)
        if isinstance(v, str) and len(v) >= 10:
            return v[:10]
    return None


def _correr_dias(fecha: str, dias: int) -> str:
    """`AAAA-MM-DD` ± días. Si no parsea, se devuelve tal cual.

    No parsear no es un error que valga la pena lanzar aquí: una fecha mal
    escrita la rechaza Oura con un 400 que explica qué esperaba, y ese mensaje
    es más útil que cualquiera que pudiéramos inventar.
    """
    try:
        return (datetime.date.fromisoformat(fecha[:10])
                + datetime.timedelta(days=dias)).isoformat()
    except ValueError:
        return fecha


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
        # SE PIDE UN DÍA DE MÁS DE CADA LADO Y SE RECORTA AQUÍ. Dos fallas
        # distintas lo obligan, las dos medidas contra la API de verdad el
        # 9-ago-2026 y las dos silenciosas:
        #
        # 1. `end_date` es INCONSISTENTE ENTRE COLECCIONES. Pidiendo [d..d]:
        #      inclusivo   daily_sleep, daily_readiness, daily_stress,
        #                  daily_spo2, daily_resilience,
        #                  daily_cardiovascular_age, sleep_time
        #      EXCLUSIVO   daily_activity, sleep, workout  <- pierden el día
        #
        # 2. `workout` (y todo lo que tenga hora) se FILTRA POR LA FECHA UTC
        #    pero reporta `day` en hora local. Con -06:00, un entrenamiento de
        #    la tarde cae en el día UTC siguiente: pedir [16..18] devolvía
        #    registros de los días 15 y 16.
        #
        # Una tabla por colección no sirve: cinco colecciones no tenían datos
        # con qué medirlas, y una tabla que Oura cambie vuelve a fallar en
        # silencio. Ensanchar y recortar es correcto en los cuatro casos —
        # inclusivo, exclusivo, y desfasado hacia cualquier lado— y lo sigue
        # siendo cuando Oura lo cambie. El costo son dos días de datos que se
        # tiran.
        if f == "rango_fecha":
            params["start_date"] = _correr_dias(inicio, -MARGEN_DIAS)
            params["end_date"] = _correr_dias(fin, +MARGEN_DIAS)
        else:
            params[f"start_{clave}"] = inicio
            params[f"end_{clave}"] = fin

    raiz = base()
    datos, paginas, siguiente = [], 0, None
    while True:
        q = dict(params)
        if siguiente:
            q["next_token"] = siguiente
        url = f"{raiz}/{coleccion}" + (f"?{urllib.parse.urlencode(q)}" if q else "")
        cuerpo = _pedir(url, token)
        paginas += 1
        # `personal_info` y `ring_configuration` no vienen envueltos en `data`.
        trozo = cuerpo.get("data") if isinstance(cuerpo.get("data"), list) else [cuerpo]
        datos.extend(trozo)
        siguiente = cuerpo.get("next_token")
        if not siguiente:
            break
        if paginas >= limite_paginas:
            datos, sobrantes = _recortar(datos, inicio, fin, f)
            return {"coleccion": coleccion, "n": len(datos), "paginas": paginas,
                    "truncado": (f"se detuvo en {limite_paginas} páginas y Oura ofrecía más; "
                                 f"acorta el rango de fechas"),
                    "continuar_desde": siguiente,
                    "datos": datos}
    datos, sobrantes = _recortar(datos, inicio, fin, f)
    salida = {"coleccion": coleccion, "n": len(datos), "paginas": paginas, "datos": datos}
    if sobrantes:
        # Se pidió un día de más para cubrir los endpoints exclusivos; éste es el
        # que se descartó. Se dice, en vez de callarlo: quien lea la respuesta
        # tiene que poder distinguir «no hay dato» de «lo quitamos nosotros».
        salida["descartados_fuera_de_rango"] = sobrantes
    return salida


def _recortar(datos: list, inicio: str | None, fin: str | None,
              f: str) -> tuple[list, int]:
    """Deja sólo los registros cuyo `day` cae en [inicio, fin].

    Devuelve (datos, cuántos se descartaron). Sólo aplica a `rango_fecha`: es el
    recorte de los dos días de más que se pidieron a propósito.

    Un registro cuyo día NO se puede determinar se conserva. Este filtro existe
    para corregir un ensanchamiento deliberado, no para decidir qué es un dato
    válido — descartar lo que no se entiende es la forma más rápida de entregar
    de menos, que es justo lo que este paquete existe para no hacer.
    """
    if f != "rango_fecha" or not (inicio and fin):
        return datos, 0
    piso, techo = inicio[:10], fin[:10]
    dentro = [r for r in datos
              if (d := dia_de(r)) is None or piso <= d <= techo]
    return dentro, len(datos) - len(dentro)
