"""Pruebas de oura-mcp.

NO TOCAN LA RED. La API de Oura se sustituye por una falsa que sirve páginas, lo
que permite probar la única cosa que de verdad importa aquí —la paginación—
contra un caso que en la vida real requeriría un mes de datos.

Un CI que necesita el token de alguien para pasar no es un CI: es una dependencia
de esa persona.
"""

import json
import io

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


# ── Que nada se lleve el token ──────────────────────────────────────────────
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
    assert cliente._token() == "token-del-archivo"


def test_el_archivo_gana_sobre_la_variable(monkeypatch, tmp_path):
    f = tmp_path / "pat"
    f.write_text("del-archivo")
    monkeypatch.setenv("OURA_PAT", "de-la-variable")
    monkeypatch.setenv("OURA_PAT_FILE", str(f))
    assert cliente._token() == "del-archivo"


def test_un_archivo_vacio_no_pasa_por_token(monkeypatch, tmp_path):
    f = tmp_path / "pat"
    f.write_text("   \n")
    monkeypatch.delenv("OURA_PAT", raising=False)
    monkeypatch.setenv("OURA_PAT_FILE", str(f))
    with pytest.raises(cliente.ErrorOura, match="vacío"):
        cliente._token()
