"""Pruebas de oura-mcp.

NO TOCAN LA RED. La API de Oura se sustituye por una falsa que sirve páginas, lo
que permite probar la única cosa que de verdad importa aquí —la paginación—
contra un caso que en la vida real requeriría un mes de datos.

Un CI que necesita el token de alguien para pasar no es un CI: es una dependencia
de esa persona.
"""

import email.message
import io
import json
import urllib.error

import pytest

from oura_mcp import cliente, colecciones


# ── El catálogo ─────────────────────────────────────────────────────────────
def test_las_diecinueve_colecciones():
    assert len(colecciones.COLECCIONES) == 19


def test_toda_coleccion_declara_una_forma_conocida():
    validas = {"rango_fecha", "rango_datetime", "unica", "solo_token"}
    for nombre, (forma, desc) in colecciones.COLECCIONES.items():
        assert forma in validas, nombre
        assert desc, nombre


def test_una_coleccion_inventada_truena_al_resolverla():
    """Tiene que fallar AQUÍ y no convertirse en una petición a una URL que no
    existe, cuyo 404 después hay que interpretar."""
    with pytest.raises(KeyError):
        colecciones.forma("daily_vibraciones")


# ── Paginación: la razón de existir del paquete ─────────────────────────────
class _RespuestaFalsa(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _oura_falso(paginas, monkeypatch, registrar=None):
    """Sustituye la API por una que sirve `paginas`, cada una con su next_token."""
    llamadas = []

    def urlopen(req, timeout=None):
        llamadas.append(req.full_url)
        if registrar is not None:
            registrar.append(req.full_url)
        i = 0
        if "next_token=" in req.full_url:
            i = int(req.full_url.split("next_token=")[1].split("&")[0])
        cuerpo = {"data": paginas[i]}
        if i + 1 < len(paginas):
            cuerpo["next_token"] = str(i + 1)
        return _RespuestaFalsa(json.dumps(cuerpo).encode())

    monkeypatch.setattr(cliente.urllib.request, "urlopen", urlopen)
    monkeypatch.setenv("OURA_PAT", "token-de-prueba")
    return llamadas


def test_sigue_el_next_token_hasta_el_final(monkeypatch):
    """LA CICATRIZ QUE JUSTIFICA EL PAQUETE. Oura entrega `next_token` y quien no
    lo persigue recibe la primera página sin que nada se lo diga: la respuesta es
    un JSON válido, con datos reales, que se ve completo.

    De siete servidores MCP de Oura publicados, el más completo no pagina."""
    paginas = [[{"i": n} for n in range(100)] for _ in range(5)]
    _oura_falso(paginas, monkeypatch)
    r = cliente.obtener("heartrate", "2026-08-01T00:00:00Z", "2026-08-02T00:00:00Z")
    assert r["n"] == 500
    assert r["paginas"] == 5
    assert "truncado" not in r


def test_al_truncar_lo_dice(monkeypatch):
    """Un resultado incompleto que no se declara incompleto es peor que un error:
    se ve igual que uno completo."""
    paginas = [[{"i": n}] for n in range(20)]
    _oura_falso(paginas, monkeypatch)
    r = cliente.obtener("heartrate", "2026-08-01T00:00:00Z", "2026-08-02T00:00:00Z",
                        limite_paginas=3)
    assert r["paginas"] == 3
    assert "truncado" in r and "acorta" in r["truncado"]


def test_una_sola_pagina_no_pide_de_mas(monkeypatch):
    llamadas = _oura_falso([[{"i": 1}]], monkeypatch)
    r = cliente.obtener("daily_sleep", "2026-08-01", "2026-08-02")
    assert r["n"] == 1 and r["paginas"] == 1
    assert len(llamadas) == 1


# ── El rango de fechas: la segunda cicatriz ─────────────────────────────────
# Medido contra la API de verdad el 9-ago-2026. `end_date` es INCONSISTENTE
# entre colecciones —daily_activity, sleep y workout pierden el último día
# pedido; las demás no— y encima `workout` se filtra por la fecha UTC mientras
# reporta `day` en hora local, así que con -06:00 un entrenamiento de la tarde
# se contaba en el día siguiente. Pedir [d..d] devolvía CERO registros sin un
# solo aviso: la misma familia de falla que no paginar.
def test_pide_dos_dias_de_mas_de_cada_lado(monkeypatch):
    """No es margen de cortesía: `workout` es exclusiva Y va desfasada a UTC, y
    las dos cosas se suman. Un día no alcanzaba."""
    urls = []
    _oura_falso([[{}]], monkeypatch, registrar=urls)
    cliente.obtener("daily_sleep", "2026-08-10", "2026-08-20")
    assert "start_date=2026-08-08" in urls[-1]
    assert "end_date=2026-08-22" in urls[-1]


def test_el_rango_datetime_no_se_ensancha(monkeypatch):
    """`heartrate` se pide con hora. Correrle dos días sería pedir mil veces más
    muestras de las que se necesitan para arreglar un problema que no tiene."""
    urls = []
    _oura_falso([[{}]], monkeypatch, registrar=urls)
    cliente.obtener("heartrate", "2026-08-10T00:00:00Z", "2026-08-10T06:00:00Z")
    assert "start_datetime=2026-08-10T00%3A00%3A00Z" in urls[-1]


def test_recorta_los_dias_de_mas_y_lo_dice(monkeypatch):
    """El día extra se pidió a propósito; descartarlo en silencio dejaría a quien
    lee la respuesta sin poder distinguir «no hay dato» de «lo quitamos»."""
    pagina = [{"day": d} for d in ("2026-08-08", "2026-08-09", "2026-08-10",
                                   "2026-08-11", "2026-08-12")]
    _oura_falso([pagina], monkeypatch)
    r = cliente.obtener("daily_sleep", "2026-08-09", "2026-08-11")
    assert [x["day"] for x in r["datos"]] == ["2026-08-09", "2026-08-10", "2026-08-11"]
    assert r["n"] == 3
    assert r["descartados_fuera_de_rango"] == 2


def test_un_solo_dia_devuelve_ese_dia(monkeypatch):
    """El caso que estaba roto: pedir [d..d] devolvía cero en daily_activity,
    sleep y workout."""
    pagina = [{"day": "2026-08-09"}, {"day": "2026-08-10"}, {"day": "2026-08-11"}]
    _oura_falso([pagina], monkeypatch)
    r = cliente.obtener("workout", "2026-08-10", "2026-08-10")
    assert r["n"] == 1 and r["datos"][0]["day"] == "2026-08-10"


def test_el_dia_sale_de_start_day_cuando_no_hay_day(monkeypatch):
    """`rest_mode_period` y `enhanced_tag` no traen `day`: traen `start_day`."""
    pagina = [{"start_day": "2026-08-09"}, {"start_day": "2026-08-30"}]
    _oura_falso([pagina], monkeypatch)
    r = cliente.obtener("enhanced_tag", "2026-08-09", "2026-08-09")
    assert r["n"] == 1


def test_lo_que_no_se_puede_fechar_se_conserva(monkeypatch):
    """Descartar lo que no se entiende es la forma más rápida de entregar de
    menos, que es exactamente lo que este paquete existe para no hacer."""
    pagina = [{"day": "2026-08-09"}, {"sin_fecha": True}, {"day": "2026-09-30"}]
    _oura_falso([pagina], monkeypatch)
    r = cliente.obtener("daily_sleep", "2026-08-09", "2026-08-09")
    assert r["n"] == 2
    assert {"sin_fecha": True} in r["datos"]


def test_dia_de_reconoce_las_claves_con_hora():
    assert cliente.dia_de({"timestamp": "2026-08-09T12:00:00-06:00"}) == "2026-08-09"
    assert cliente.dia_de({"bedtime_start": "2026-08-09T23:10:00-06:00"}) == "2026-08-09"
    assert cliente.dia_de({"nada": 1}) is None
    assert cliente.dia_de("no es un dict") is None


def test_al_truncar_deja_el_cursor_para_continuar(monkeypatch):
    """`truncado` avisaba pero no dejaba continuar: quien lo recibía sólo podía
    reintentar a ciegas."""
    paginas = [[{"i": n}] for n in range(20)]
    _oura_falso(paginas, monkeypatch)
    r = cliente.obtener("heartrate", "2026-08-01T00:00:00Z", "2026-08-02T00:00:00Z",
                        limite_paginas=3)
    assert r["continuar_desde"] == "3"


# ── CSV: el mismo dato sin repetir las claves 37,000 veces ──────────────────
def test_el_encabezado_sale_de_la_union_no_del_primero(monkeypatch):
    """Sacar el encabezado del primer registro es la forma más fácil de perder
    datos aquí: basta un registro con un campo extra para que ese campo
    desaparezca sin dejar rastro."""
    _oura_falso([[{"day": "2026-08-10", "score": 1},
                  {"day": "2026-08-11", "score": 2, "extra": 9}]], monkeypatch)
    r = cliente.obtener("daily_sleep", "2026-08-10", "2026-08-11", formato="csv")
    assert "extra" in r["columnas"]
    assert "9" in r["datos"]


def test_avisa_cuando_los_registros_no_traen_las_mismas_claves(monkeypatch):
    """Una celda vacía puede ser «campo ausente» o «valor nulo». Con registros de
    distinta forma la diferencia importa y callarla aparenta regularidad."""
    _oura_falso([[{"day": "2026-08-10"}, {"day": "2026-08-11", "extra": 1}]], monkeypatch)
    r = cliente.obtener("daily_sleep", "2026-08-10", "2026-08-11", formato="csv")
    assert "columnas_desiguales" in r
    _oura_falso([[{"day": "2026-08-10"}, {"day": "2026-08-11"}]], monkeypatch)
    r = cliente.obtener("daily_sleep", "2026-08-10", "2026-08-11", formato="csv")
    assert "columnas_desiguales" not in r


def test_lo_anidado_va_como_json_en_su_celda(monkeypatch):
    """Aplanar inventaría columnas que Oura no tiene; omitir sería perder datos."""
    _oura_falso([[{"day": "2026-08-10", "contributors": {"deep": 91}}]], monkeypatch)
    r = cliente.obtener("daily_sleep", "2026-08-10", "2026-08-10", formato="csv")
    assert '{""deep"":91}' in r["datos"]


def test_la_fecha_es_la_primera_columna(monkeypatch):
    """Es la columna con la que se cruza contra otra fuente."""
    _oura_falso([[{"score": 1, "day": "2026-08-10", "aaa": 2}]], monkeypatch)
    r = cliente.obtener("daily_sleep", "2026-08-10", "2026-08-10", formato="csv")
    assert r["columnas"][0] == "day"


def test_el_csv_tambien_llega_cuando_se_trunca(monkeypatch):
    """Con dos salidas, la truncada se iba sin formato ni avisos — y es la que
    más necesita que se le crea todo lo que dice."""
    paginas = [[{"day": "2026-08-10", "i": n}] for n in range(20)]
    _oura_falso(paginas, monkeypatch)
    r = cliente.obtener("daily_sleep", "2026-08-10", "2026-08-10",
                        formato="csv", limite_paginas=3)
    assert r["formato"] == "csv" and "truncado" in r and r["continuar_desde"] == "3"


# ── El 429: reintento acotado ───────────────────────────────────────────────
# Oura NO manda cabeceras de límite de tasa en las respuestas buenas —verificado
# el 9-ago-2026— así que un cliente no puede saber qué tan cerca está del tope.
# Sólo se entera cuando ya se lo negaron, y para entonces puede llevar 30
# páginas traídas que se tirarían a la basura.
def _falla_n_veces(monkeypatch, veces, cabeceras=None, dormidas=None):
    if dormidas is None:
        dormidas = []
    estado = {"n": 0}

    def urlopen(req, timeout=None):
        if estado["n"] < veces:
            estado["n"] += 1
            raise urllib.error.HTTPError(
                req.full_url, 429, "Too Many Requests",
                email.message.Message() if cabeceras is None else cabeceras, None)
        return _RespuestaFalsa(json.dumps({"data": [{"ok": 1}]}).encode())

    monkeypatch.setattr(cliente.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(cliente.time, "sleep", dormidas.append)
    monkeypatch.setenv("OURA_PAT", "x")
    return estado


def test_reintenta_el_429_y_sale_adelante(monkeypatch):
    dormidas = []
    _falla_n_veces(monkeypatch, 2, dormidas=dormidas)
    assert cliente.obtener("personal_info")["n"] == 1
    assert dormidas == [1.0, 2.0]          # backoff exponencial


def test_el_429_persistente_se_rinde_con_todo_dicho(monkeypatch):
    _falla_n_veces(monkeypatch, 99)
    with pytest.raises(cliente.ErrorOura, match="2 reintentos"):
        cliente.obtener("personal_info")


def test_honra_retry_after_en_segundos(monkeypatch):
    cab = email.message.Message()
    cab["Retry-After"] = "3"
    dormidas = []
    _falla_n_veces(monkeypatch, 1, cabeceras=cab, dormidas=dormidas)
    cliente.obtener("personal_info")
    assert dormidas == [3.0]


def test_el_retry_after_no_puede_colgar_la_conversacion(monkeypatch):
    """Una cabecera que pida media hora no puede dejar esperando a nadie."""
    cab = email.message.Message()
    cab["Retry-After"] = "1800"
    dormidas = []
    _falla_n_veces(monkeypatch, 1, cabeceras=cab, dormidas=dormidas)
    cliente.obtener("personal_info")
    assert dormidas == [cliente.ESPERA_MAXIMA]


def test_solo_el_429_se_reintenta(monkeypatch):
    """Un 401 no mejora esperando: reintentarlo sólo tarda tres veces más en dar
    la misma mala noticia."""
    intentos = {"n": 0}

    def urlopen(req, timeout=None):
        intentos["n"] += 1
        raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized",
                                     email.message.Message(), None)

    monkeypatch.setattr(cliente.urllib.request, "urlopen", urlopen)
    monkeypatch.setenv("OURA_PAT", "x")
    with pytest.raises(cliente.ErrorOura, match="401"):
        cliente.obtener("personal_info")
    assert intentos["n"] == 1


# ── `fields` y `latest`: los dos que Oura ignora en silencio ────────────────
# Medido contra la API el 9-ago-2026. Los dos fallan igual: no dan error, dan
# de más. `fields=no_existe` devuelve el registro COMPLETO —la proyección no
# ocurre— y `latest=true` en una colección que no lo soporta devuelve la
# colección entera. Quien pidió cree que filtró, y no filtró.
def test_los_campos_van_como_fields(monkeypatch):
    urls = []
    _oura_falso([[{"day": "2026-08-10", "score": 1}]], monkeypatch, registrar=urls)
    cliente.obtener("daily_sleep", "2026-08-10", "2026-08-10", campos=["score", "day"])
    assert "fields=score%2Cday" in urls[-1]


def test_avisa_de_los_campos_que_no_aparecieron(monkeypatch):
    _oura_falso([[{"day": "2026-08-10", "score": 1}]], monkeypatch)
    r = cliente.obtener("daily_sleep", "2026-08-10", "2026-08-10",
                        campos=["score", "no_existe"])
    assert r["campos_ignorados"] == ["no_existe"]


def test_sin_campos_pedidos_no_hay_aviso(monkeypatch):
    _oura_falso([[{"day": "2026-08-10"}]], monkeypatch)
    r = cliente.obtener("daily_sleep", "2026-08-10", "2026-08-10")
    assert "campos_ignorados" not in r


def test_ultimo_solo_donde_oura_lo_respeta(monkeypatch):
    urls = []
    _oura_falso([[{"bpm": 60}]], monkeypatch, registrar=urls)
    cliente.obtener("heartrate", ultimo=True)
    assert "latest=true" in urls[-1]


def test_ultimo_se_rechaza_donde_oura_lo_ignora(monkeypatch):
    """Rechazarlo AQUÍ y no dejar que Oura devuelva la colección entera: pedir el
    último registro y recibir diez creyendo que es uno es peor que un error."""
    _oura_falso([[{}]], monkeypatch)
    with pytest.raises(cliente.ErrorOura, match="lo ignora"):
        cliente.obtener("daily_sleep", "2026-08-01", "2026-08-10", ultimo=True)


def test_ultimo_no_exige_rango(monkeypatch):
    """`latest` no necesita fechas, y exigirlas sería inventar un requisito."""
    _oura_falso([[{"bpm": 60}]], monkeypatch)
    assert cliente.obtener("ring_battery_level", ultimo=True)["n"] == 1


# ── El sandbox: probarlo sin tener con qué autenticarse ─────────────────────
# Oura deprecó los tokens personales en diciembre de 2025. Quien llega hoy no
# tiene cómo conseguir uno, así que «instálalo y luego consigue un token» dejó
# de ser un camino. El sandbox es oficial —está en el OpenAPI, con 34 rutas
# espejo— y acepta cualquier cadena como Authorization.
def test_el_sandbox_no_pide_token(monkeypatch):
    monkeypatch.delenv("OURA_PAT", raising=False)
    monkeypatch.delenv("OURA_PAT_FILE", raising=False)
    monkeypatch.setenv("OURA_SANDBOX", "1")
    assert cliente._token().revelar() == "sandbox"


def test_el_sandbox_cambia_la_base(monkeypatch):
    monkeypatch.setenv("OURA_SANDBOX", "1")
    assert cliente.base().endswith("/v2/sandbox/usercollection")
    monkeypatch.setenv("OURA_SANDBOX", "0")
    assert cliente.base().endswith("/v2/usercollection")


def test_la_base_se_puede_forzar(monkeypatch):
    """`OURA_API_BASE_URL` gana sobre todo: es lo que permite apuntar a un doble
    en una prueba sin monkeypatchear el módulo."""
    monkeypatch.setenv("OURA_SANDBOX", "1")
    monkeypatch.setenv("OURA_API_BASE_URL", "http://localhost:9999/v2/x/")
    assert cliente.base() == "http://localhost:9999/v2/x"


def test_apagado_el_sandbox_el_token_vuelve_a_ser_obligatorio(monkeypatch):
    monkeypatch.delenv("OURA_PAT", raising=False)
    monkeypatch.delenv("OURA_PAT_FILE", raising=False)
    monkeypatch.delenv("OURA_SANDBOX", raising=False)
    with pytest.raises(cliente.ErrorOura, match="personal-access-tokens"):
        cliente._token()


# ── Parámetros ──────────────────────────────────────────────────────────────
def test_las_de_fecha_exigen_rango(monkeypatch):
    monkeypatch.setenv("OURA_PAT", "x")
    with pytest.raises(cliente.ErrorOura, match="necesita inicio y fin"):
        cliente.obtener("daily_sleep")


def test_cada_forma_manda_el_parametro_que_le_toca(monkeypatch):
    """`daily_*` usa start_date; `heartrate` usa start_datetime. Mandar el
    equivocado devuelve un 400 que después hay que descifrar."""
    urls = []
    _oura_falso([[{}]], monkeypatch, registrar=urls)
    cliente.obtener("daily_sleep", "2026-08-01", "2026-08-02")
    assert "start_date=" in urls[-1] and "start_datetime=" not in urls[-1]
    cliente.obtener("heartrate", "2026-08-01T00:00:00Z", "2026-08-02T00:00:00Z")
    assert "start_datetime=" in urls[-1]
    cliente.obtener("personal_info")
    assert "?" not in urls[-1]      # sin rango no se inventan parámetros


def test_sin_token_dice_donde_conseguirlo(monkeypatch):
    monkeypatch.delenv("OURA_PAT", raising=False)
    with pytest.raises(cliente.ErrorOura, match="personal-access-tokens"):
        cliente.obtener("personal_info")


# ── `dia`: que la consulta más común no obligue a escribir un rango ─────────
def test_dia_equivale_a_inicio_igual_a_fin(monkeypatch):
    _oura_falso([[{"day": "2026-08-09"}, {"day": "2026-08-10"}]], monkeypatch)
    from oura_mcp.servidor import oura_consultar
    f = getattr(oura_consultar, "fn", oura_consultar)
    r = f(coleccion="workout", dia="2026-08-10")
    assert r["n"] == 1 and r["datos"][0]["day"] == "2026-08-10"


def test_dia_y_rango_juntos_es_un_error(monkeypatch):
    """Mezclar los dos no tiene una interpretación obvia, y elegir una en
    silencio es cómo se cuelan los rangos equivocados."""
    _oura_falso([[{}]], monkeypatch)
    from oura_mcp.servidor import oura_consultar
    f = getattr(oura_consultar, "fn", oura_consultar)
    assert "no ambos" in f(coleccion="workout", dia="2026-08-10",
                           inicio="2026-08-01")["error"]


# ── Anotaciones: lo que el cliente MCP necesita saber sin preguntar ─────────
def test_las_tres_se_declaran_de_solo_lectura():
    """No es una promesa: no hay un POST, ni un PUT, ni un DELETE en todo el
    paquete. Declararlo evita que el cliente confirme en cada llamada, y el
    directorio de conectores de Claude lo exige."""
    import asyncio
    from oura_mcp.servidor import servidor
    herramientas = asyncio.run(servidor.list_tools())
    assert len(herramientas) == 3
    for t in herramientas:
        assert t.title, t.name
        assert t.annotations.read_only_hint is True, t.name
        assert t.annotations.destructive_hint is False, t.name
        # Los datos vienen de un servicio externo: la misma llamada dos veces
        # puede diferir si el anillo sincronizó en medio. Decir lo contrario
        # sería invitar a que alguien memoice la respuesta.
        assert t.annotations.open_world_hint is True, t.name


def test_no_hay_una_sola_escritura_en_el_paquete():
    """La anotación de sólo lectura tiene que seguir siendo verdad cuando alguien
    agregue código. Esta prueba es la que se entera."""
    import pathlib
    raiz = pathlib.Path(__file__).parent.parent / "src" / "oura_mcp"
    for archivo in raiz.glob("*.py"):
        texto = archivo.read_text(encoding="utf-8")
        for verbo in ('"POST"', "'POST'", '"PUT"', "'PUT'", '"DELETE"', "'DELETE'",
                      '"PATCH"', "'PATCH'"):
            assert verbo not in texto, f"{archivo.name} trae {verbo}"


# ── Que nada se lleve el token ──────────────────────────────────────────────
def test_el_token_no_se_imprime_por_accidente():
    """Un str con el token adentro sale solo por demasiados lados: el repr de las
    locales en una traza, un print de depuración que se quedó, un f-string
    escrito de prisa. Aquí ya costó un token una vez."""
    s = cliente.Secreto("abcdefghij")
    assert "abcdefghij" not in repr(s)
    assert "abcdefghij" not in str(s)
    assert "abcdefghij" not in f"{s}"
    assert "abcdefghij" not in "{}".format(s)
    assert "10" in repr(s)              # la longitud sí, que es lo que diagnostica
    assert s.revelar() == "abcdefghij"  # revelarlo es explícito y se puede grepear


def test_el_secreto_sabe_cuanto_mide():
    """`--revisar` reporta la longitud del token, nunca el token."""
    assert len(cliente.Secreto("abc")) == 3



def test_el_error_nunca_lleva_el_token(monkeypatch):
    """Los mensajes de error son lo que más se copia y se pega. El token va en un
    encabezado y no tiene por qué salir de ahí jamás."""
    monkeypatch.setenv("OURA_PAT", "token-secretisimo-12345")

    def revienta(req, timeout=None):
        raise cliente.urllib.error.HTTPError(req.full_url, 401, "no", {}, None)

    monkeypatch.setattr(cliente.urllib.request, "urlopen", revienta)
    with pytest.raises(cliente.ErrorOura) as e:
        cliente.obtener("personal_info")
    assert "token-secretisimo-12345" not in str(e.value)


def test_revisar_reporta_el_largo_del_token_no_el_token(monkeypatch):
    from oura_mcp import servidor
    monkeypatch.setenv("OURA_PAT", "token-secretisimo-12345")
    monkeypatch.setattr(servidor, "obtener",
                        lambda *a, **k: {"datos": [{"age": 39, "email": "x@y.z"}]})
    r = servidor.revisar()
    texto = json.dumps(r)
    assert "token-secretisimo-12345" not in texto
    assert r["token_largo"] == len("token-secretisimo-12345")
    # Y de la respuesta sólo los NOMBRES de los campos, nunca los valores.
    assert r["campos_del_perfil"] == ["age", "email"]
    assert "x@y.z" not in texto and "39" not in texto


def test_el_token_puede_venir_de_un_archivo(monkeypatch, tmp_path):
    """Un servidor MCP se registra en un JSON de configuración, y meter ahí el
    token lo deja en claro en un archivo que se respalda, se sincroniza y se
    comparte al pedir ayuda. El archivo aparte se rota sin tocar la config."""
    f = tmp_path / "pat"
    f.write_text("token-del-archivo\n")
    monkeypatch.delenv("OURA_PAT", raising=False)
    monkeypatch.setenv("OURA_PAT_FILE", str(f))
    assert cliente._token().revelar() == "token-del-archivo"


def test_el_archivo_gana_sobre_la_variable(monkeypatch, tmp_path):
    f = tmp_path / "pat"
    f.write_text("del-archivo")
    monkeypatch.setenv("OURA_PAT", "de-la-variable")
    monkeypatch.setenv("OURA_PAT_FILE", str(f))
    assert cliente._token().revelar() == "del-archivo"


def test_un_archivo_vacio_no_pasa_por_token(monkeypatch, tmp_path):
    f = tmp_path / "pat"
    f.write_text("   \n")
    monkeypatch.delenv("OURA_PAT", raising=False)
    monkeypatch.setenv("OURA_PAT_FILE", str(f))
    with pytest.raises(cliente.ErrorOura, match="vacío"):
        cliente._token()
