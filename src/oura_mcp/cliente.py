"""Cliente de la API v2 de Oura. Sin dependencias: sólo biblioteca estándar.

LO ÚNICO QUE IMPORTA DE ESTE ARCHIVO ES LA PAGINACIÓN.

Oura entrega `{"data": [...], "next_token": "..."}`. Si `next_token` viene y no
lo sigues, recibes la primera página y **nada te avisa**: la respuesta es un JSON
válido, con datos reales, que se ve completo. Para `heartrate`, que muestrea cada
cinco minutos, un mes son ~8,600 puntos y la primera página trae una fracción.

No es hipotético: medido el 9-ago-2026, un día local de `heartrate` son **1,231
muestras en 2 páginas**. Quien no pagina recibe 1,000 de 1,231 —el 81%— con
aspecto de estar completo. Es el mismo error que PostgREST castiga con su tope
de 1,000 filas y que ya costó caro en este proyecto, tres veces.

Por eso aquí la paginación no es una opción del llamador: es el único camino.
`obtener()` no devuelve hasta que `next_token` viene vacío, o hasta toparse con
`limite_paginas` — y en ese caso lo DICE, en vez de callarse.

Y hay un tercer final, que es el que casi se nos escapa: si Oura repite el mismo
`next_token`, eso es un ciclo. Sin detectarlo se hacían 50 peticiones idénticas
y se devolvían 50 copias del mismo registro, con un aviso que aconsejaba acortar
el rango — consejo inútil, porque acortar no arregla que la API se repita.
"""

from __future__ import annotations

import csv
import datetime
import email.utils
import io
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from .colecciones import BASE, CON_FECHA, CON_ULTIMO, forma

TIEMPO_LIMITE = 30
LIMITE_PAGINAS = 50          # ~50k registros; más que eso es un error de uso
REINTENTOS_429 = 2           # acotado: esto corre dentro de una conversación
ESPERA_MAXIMA = 8.0          # segundos; ni el `Retry-After` de Oura manda más

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


class Secreto:
    """Un token que no se imprime por accidente. Hay que pedirlo con `revelar()`.

    Un `str` con el token adentro sale solo por demasiados lados: el `repr` de
    las variables locales que imprimen algunos formateadores de traza, un
    `print` de depuración que se quedó, una excepción que arrastra su contexto,
    un f-string escrito de prisa.

    Aquí ya costó un token una vez —un `~/.pypirc` mal formado hizo que el
    parser volcara el token completo a un transcript, el 9-ago-2026— y la
    lección no fue «ten más cuidado»: fue que el cuidado no se puede sostener a
    mano. Con esta clase, imprimirlo sin querer es imposible; revelarlo es una
    llamada explícita que se ve en el código y se puede buscar con grep.
    """

    __slots__ = ("_valor",)

    def __init__(self, valor: str):
        self._valor = valor

    def revelar(self) -> str:
        return self._valor

    def __len__(self) -> int:
        return len(self._valor)

    def __repr__(self) -> str:
        return f"<secreto de {len(self._valor)} caracteres>"

    __str__ = __repr__


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


def _token() -> Secreto:
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
        return Secreto("sandbox")
    ruta = (os.environ.get("OURA_PAT_FILE") or "").strip()
    if ruta:
        try:
            t = open(os.path.expanduser(ruta), encoding="utf-8").read().strip()
        except OSError as e:
            raise ErrorOura(f"no se pudo leer OURA_PAT_FILE: {e.strerror}") from None
        if not t:
            raise ErrorOura(f"OURA_PAT_FILE apunta a un archivo vacío: {ruta}")
        return Secreto(t)
    t = (os.environ.get("OURA_PAT") or "").strip()
    if t:
        return Secreto(t)
    return _token_de_oauth()


def _token_de_oauth() -> Secreto:
    """El access token de OAuth2, renovándolo si hace falta.

    Se importa aquí adentro y no arriba porque `credenciales` importa de este
    módulo. La alternativa era partir `Secreto` y `ErrorOura` a un tercer
    archivo, que es más ceremonia de la que justifica un import diferido.
    """
    from .credenciales import cargar, refrescar

    cred = cargar()
    if cred is None:
        # EL MENSAJE IMPORTA. Antes mandaba a la página de tokens personales, y
        # desde diciembre de 2025 esa página ya no deja crear ninguno: quien
        # llegara ahí se quedaba atorado sin saber por qué. Ahora la primera
        # opción es la que funciona, y el sandbox va antes que nada porque
        # permite ver el servidor andar sin conseguir credencial alguna.
        raise ErrorOura(
            "no hay credenciales. Tres caminos, de menos a más trámite:\n"
            "  1. OURA_SANDBOX=1 — datos de ejemplo, sin registrarte en nada\n"
            "  2. oura-mcp --autorizar — OAuth2, una vez, en el navegador\n"
            "  3. OURA_PAT / OURA_PAT_FILE — sólo si ya tenías un token "
            "personal: Oura dejó de emitirlos en diciembre de 2025"
        )
    if not cred.caducado():
        return cred.acceso
    from .autorizar import credenciales_de_app
    cid, csec = credenciales_de_app()
    return refrescar(cred, cid, csec).acceso


def _espera_pedida(e: urllib.error.HTTPError, intento: int) -> float:
    """Cuánto esperar tras un 429: lo que diga `Retry-After`, o backoff.

    `Retry-After` admite dos formas —segundos, o una fecha HTTP— y Oura no
    documenta cuál manda. Se aceptan las dos, y si no viene ninguna se usa
    backoff exponencial, que es lo único razonable cuando el servidor no dice
    nada. Se acota a `ESPERA_MAXIMA`: una cabecera que pida media hora no puede
    dejar colgada una conversación.
    """
    cabecera = (e.headers.get("Retry-After") or "").strip() if e.headers else ""
    if cabecera:
        try:
            return min(float(cabecera), ESPERA_MAXIMA)
        except ValueError:
            pass
        try:
            cuando = email.utils.parsedate_to_datetime(cabecera)
            faltan = (cuando - datetime.datetime.now(cuando.tzinfo)).total_seconds()
            return min(max(faltan, 0.0), ESPERA_MAXIMA)
        except (TypeError, ValueError):
            pass
    return min(2.0 ** intento, ESPERA_MAXIMA)


def _detalle_de(e: urllib.error.HTTPError) -> str:
    """Lo legible del cuerpo de error de Oura, o el crudo recortado.

    Oura contesta `detail` de dos formas distintas y ninguna se lee bien en
    crudo. Una es una cadena; la otra es el arreglo de errores de validación de
    pydantic, cuyo JSON pasa de los 200 caracteres antes de llegar a lo único
    que importa —qué campo y por qué—, así que recortarlo dejaba al usuario con
    `{"detail":[{"type":"datetime_from_date_parsing","loc":["query","star` y
    nada más.
    """
    try:
        cuerpo = json.loads(e.read().decode("utf-8", "replace"))
    except Exception:
        return ""
    d = cuerpo.get("detail") if isinstance(cuerpo, dict) else None
    if isinstance(d, str):
        return ": " + d[:200]
    if isinstance(d, list):
        partes = []
        for item in d[:2]:              # dos bastan: el resto repite el mismo campo
            if not isinstance(item, dict):
                continue
            campo = ".".join(str(x) for x in (item.get("loc") or [])[1:2]) or "?"
            msg = item.get("msg") or ""
            recibido = item.get("input")
            partes.append(f"{campo}: {msg}"
                          + (f" (recibido: {recibido!r})" if recibido is not None else ""))
        if partes:
            return ": " + "; ".join(partes)[:200]
    return ": " + json.dumps(cuerpo, ensure_ascii=False)[:200]


def _pedir(url: str, token: Secreto, reintentos: int = REINTENTOS_429) -> dict:
    """Una petición a Oura, con reintento acotado sólo para el 429.

    SÓLO el 429 se reintenta. Un 401 no mejora esperando y un 400 tampoco: lo
    único que consigue reintentarlos es tardar tres veces más en dar la misma
    mala noticia.

    Oura NO manda cabeceras de límite de tasa en las respuestas buenas
    —verificado el 9-ago-2026: ni `X-RateLimit-Remaining` ni equivalente— así
    que un cliente no puede saber qué tan cerca está del tope. Sólo se entera
    cuando ya se lo negaron. Para una consulta que puede encadenar 50 páginas,
    rendirse al primer 429 tira a la basura todo lo ya traído.
    """
    req = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {token.revelar()}",
                 "Accept": "application/json"}
    )
    for intento in range(reintentos + 1):
        try:
            with urllib.request.urlopen(req, timeout=TIEMPO_LIMITE) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429 and intento < reintentos:
                time.sleep(_espera_pedida(e, intento))
                continue
            # El cuerpo del error de Oura explica la causa (rango inválido,
            # permiso faltante). Se pasa recortado a 200 caracteres: un mensaje
            # de error es lo que más se copia y se pega, y no tiene por qué
            # arrastrar más.
            detalle = _detalle_de(e)
            if e.code == 401:
                raise ErrorOura("Oura rechazó el token (401). ¿Expiró el PAT?") from None
            if e.code == 429:
                raise ErrorOura(
                    f"Oura está limitando la tasa (429) y siguió limitándola tras "
                    f"{reintentos} reintentos. Espera un poco y acorta el rango."
                ) from None
            raise ErrorOura(f"Oura respondió {e.code}{detalle}") from None
        except urllib.error.URLError as e:
            raise ErrorOura(f"no se pudo alcanzar Oura: {e.reason}") from None
    raise ErrorOura("Oura no respondió")   # inalcanzable; el bucle siempre sale


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
            campos: list[str] | None = None, ultimo: bool = False,
            formato: str = "json", limite_paginas: int = LIMITE_PAGINAS) -> dict:
    """Trae una colección COMPLETA, siguiendo `next_token` hasta el final.

    Devuelve `{"coleccion", "n", "paginas", "datos", ["truncado"]}`.

    La clave `truncado` sólo aparece si se agotaron las páginas permitidas. Un
    resultado incompleto que no se declara incompleto es el peor de los dos
    mundos: se ve igual que uno completo.
    """
    f = forma(coleccion)
    token = _token()
    params: dict[str, str] = {}

    if ultimo:
        # Oura NO se queja si se le manda `latest` a una colección que no lo
        # soporta: devuelve la colección entera. Pedir el último registro y
        # recibir diez creyendo que es uno es peor que un error.
        if coleccion not in CON_ULTIMO:
            raise ErrorOura(
                f"`ultimo` sólo lo respeta Oura en {', '.join(sorted(CON_ULTIMO))}; "
                f"en {coleccion} lo ignora y devuelve la colección entera"
            )
        params["latest"] = "true"
    if campos:
        params["fields"] = ",".join(campos)

    if f in CON_FECHA and not ultimo:
        if not inicio or not fin:
            raise ErrorOura(f"{coleccion} necesita inicio y fin")
        if inicio > fin:
            # Se atrapa AQUÍ y no en Oura porque el margen de MARGEN_DIAS cambia
            # las fechas: Oura devolvería un 400 citando dos fechas que quien
            # preguntó nunca escribió, y diagnosticar eso cuesta más que el
            # error mismo.
            raise ErrorOura(
                f"el rango va al revés: inicio ({inicio}) es posterior a fin ({fin})"
            )
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
    truncado, cursor, ciclo = None, None, None
    vistos: set[str] = set()
    while True:
        q = dict(params)
        if siguiente:
            q["next_token"] = siguiente
        url = f"{raiz}/{coleccion}" + (f"?{urllib.parse.urlencode(q)}" if q else "")
        cuerpo = _pedir(url, token)
        paginas += 1
        # `personal_info` y `ring_configuration` no vienen envueltos en `data`:
        # el cuerpo ENTERO es el registro. Se distingue por la AUSENCIA de la
        # clave, no por que no sea lista. La diferencia importa: si `data` viene
        # y no es una lista, algo cambió en la API, y envolver el sobre entero
        # convertiría eso en «un registro» con forma `{"data": …}` que se ve
        # legítimo. Callarlo sería la falla de siempre, cometida por nosotros.
        if "data" in cuerpo:
            crudo = cuerpo["data"]
            if isinstance(crudo, list):
                trozo = crudo
            else:
                raise ErrorOura(
                    f"Oura devolvió `data` como {type(crudo).__name__} y no como "
                    f"lista en {coleccion}. La forma de la respuesta cambió; no "
                    f"se inventa una interpretación."
                )
        else:
            trozo = [cuerpo] if cuerpo else []
        datos.extend(trozo)
        siguiente = cuerpo.get("next_token")
        if not siguiente:
            break
        if siguiente in vistos:
            # UN `next_token` QUE SE REPITE ES UN CICLO. Sin esto se hacían 50
            # peticiones idénticas, se devolvían 50 copias del mismo registro, y
            # el aviso decía «acorta el rango» — consejo inútil, porque acortar
            # no arregla que la API se repita. Y encima quema 49 peticiones
            # contra un límite de tasa que Oura no anuncia por ninguna cabecera.
            #
            # No es truncamiento y no debe llamarse así: es la API portándose
            # mal. Se dice tal cual, con lo que se alcanzó a traer.
            ciclo = ("Oura repitió el mismo `next_token`: eso es un ciclo, y se "
                     "paró para no pedir lo mismo sin fin. Lo que sigue llega "
                     "hasta donde se pudo avanzar y puede estar incompleto.")
            break
        vistos.add(siguiente)
        if paginas >= limite_paginas:
            # UNA SOLA SALIDA. Con dos, la truncada se iba sin pasar por el
            # formato ni por los avisos — y es justo la respuesta que más
            # necesita que se le crea todo lo que dice.
            truncado, cursor = (
                f"se detuvo en {limite_paginas} páginas y Oura ofrecía más; "
                f"acorta el rango o sigue desde `continuar_desde`"), siguiente
            break

    datos, sobrantes = _recortar(datos, inicio, fin, f)
    salida = {"coleccion": coleccion, "n": len(datos), "paginas": paginas, "datos": datos}
    if truncado:
        salida["truncado"] = truncado
        salida["continuar_desde"] = cursor
    if ciclo:
        salida["ciclo_de_paginacion"] = ciclo
    if formato == "csv":
        texto, columnas, heterogeneos = a_csv(datos)
        salida["datos"] = texto
        salida["formato"] = "csv"
        salida["columnas"] = columnas
        if heterogeneos:
            # Una celda vacía puede ser «no vino el campo» o «vino en nulo». Con
            # registros de distinta forma la diferencia importa, y callarla sería
            # entregar una tabla que aparenta más regularidad de la que hay.
            salida["columnas_desiguales"] = (
                "no todos los registros traen las mismas claves; una celda vacía "
                "puede ser campo ausente o valor nulo"
            )
    if (ignorados := _campos_ignorados(campos, datos)):
        salida["campos_ignorados"] = ignorados
    if sobrantes:
        # Se pidió un día de más para cubrir los endpoints exclusivos; éste es el
        # que se descartó. Se dice, en vez de callarlo: quien lea la respuesta
        # tiene que poder distinguir «no hay dato» de «lo quitamos nosotros».
        salida["descartados_fuera_de_rango"] = sobrantes
    return salida


def a_csv(datos: list) -> tuple[str, list[str], bool]:
    """Los registros como CSV. Devuelve (texto, columnas, si_son_heterogeneos).

    Un mes de `heartrate` son ~37,000 registros; en JSON eso repite las mismas
    cuatro claves 37,000 veces. El CSV las escribe una vez.

    EL ENCABEZADO SALE DE LA UNIÓN DE TODAS LAS CLAVES, no del primer registro.
    Sacarlo del primero es la forma más fácil de perder datos aquí: basta un
    registro con un campo extra para que ese campo desaparezca sin dejar rastro,
    que es exactamente el tipo de falla que este paquete existe para no cometer.

    Los valores anidados —`contributors` y compañía— se escriben como JSON en su
    celda. Aplanarlos inventaría columnas que Oura no tiene; omitirlos sería
    perder datos.
    """
    filas = [r for r in datos if isinstance(r, dict)]
    claves = set()
    for r in filas:
        claves |= set(r)
    # La fecha primero: es la columna con la que un modelo cruza contra otra
    # fuente, y buscarla a mitad de la tabla es fricción sin motivo.
    delante = [k for k in ("day", "timestamp", "start_day", "id") if k in claves]
    columnas = delante + sorted(claves - set(delante))
    heterogeneos = any(set(r) != claves for r in filas)

    buf = io.StringIO()
    escritor = csv.writer(buf, lineterminator="\n")
    escritor.writerow(columnas)
    for r in filas:
        escritor.writerow([_celda(r.get(c)) for c in columnas])
    return buf.getvalue(), columnas, heterogeneos


def _celda(v) -> str:
    if v is None:
        return ""
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False, separators=(",", ":"))
    return str(v)


def _campos_ignorados(campos: list[str] | None, datos: list) -> list[str]:
    """Los campos pedidos que no aparecieron en ningún registro.

    Oura NO se queja de un nombre de campo que no existe. Medido el 9-ago-2026:
    `fields=no_existe` devuelve el registro COMPLETO —la proyección no ocurre— y
    `fields=score,no_existe` aplica el bueno y tira el malo sin decir nada. En
    los dos casos quien pidió cree haber filtrado y no filtró.

    Se avisa en vez de fallar: un campo puede faltar legítimamente porque no hay
    dato. Por eso el nombre es «no aparecieron», no «no existen».
    """
    if not campos or not datos:
        return []
    presentes = set()
    for r in datos:
        if isinstance(r, dict):
            presentes |= set(r)
    return sorted(c for c in campos if c not in presentes)


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
