"""oura-mcp tests.

THEY NEVER TOUCH THE NETWORK. Oura's API is replaced by a fake one that serves
pages, which allows testing the one thing that genuinely matters here — the
pagination — against a case that in real life would need a month of data.

A CI that needs someone's token to pass is not a CI: it is a dependency on that
person.
"""

import email.message
import io
import json
import urllib.error

import pytest

from oura_mcp import client, collections


# ── The catalog ────────────────────────────────────────────────────────────
def test_las_diecinueve_colecciones():
    assert len(collections.COLLECTIONS) == 19


def test_toda_coleccion_declara_una_forma_conocida():
    validas = {"date_range", "datetime_range", "single", "token_only"}
    for nombre, (shape, desc) in collections.COLLECTIONS.items():
        assert shape in validas, nombre
        assert desc, nombre


def test_a_made_up_collection_blows_up_when_resolved():
    """It has to fail HERE and not turn into a request to a URL that doesn't
    exist, whose 404 then has to be interpreted."""
    with pytest.raises(KeyError):
        collections.shape("daily_vibraciones")


# ── Pagination: the package's reason to exist ──────────────────────────────
class _RespuestaFalsa(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fake_oura(pages, monkeypatch, registrar=None):
    """Replaces the API with one serving `pages`, each with its own next_token."""
    llamadas = []

    def urlopen(req, timeout=None):
        llamadas.append(req.full_url)
        if registrar is not None:
            registrar.append(req.full_url)
        i = 0
        if "next_token=" in req.full_url:
            i = int(req.full_url.split("next_token=")[1].split("&")[0])
        cuerpo = {"data": pages[i]}
        if i + 1 < len(pages):
            cuerpo["next_token"] = str(i + 1)
        return _RespuestaFalsa(json.dumps(cuerpo).encode())

    monkeypatch.setattr(client.urllib.request, "urlopen", urlopen)
    monkeypatch.setenv("OURA_PAT", "token-de-prueba")
    return llamadas


def test_follows_next_token_to_the_end(monkeypatch):
    """THE SCAR THAT JUSTIFIES THE PACKAGE. Oura returns `next_token` and whoever
    does not chase it receives the first page with nothing saying so: the
    response is valid JSON, with real data, that looks complete."""
    pages = [[{"i": n} for n in range(100)] for _ in range(5)]
    _fake_oura(pages, monkeypatch)
    r = client.fetch("heartrate", "2026-08-01T00:00:00Z", "2026-08-02T00:00:00Z")
    assert r["n"] == 500
    assert r["pages"] == 5
    assert "truncated" not in r


def test_says_so_when_truncating(monkeypatch):
    """An incomplete result that doesn't declare itself incomplete is worse than an
    error: it looks exactly like a complete one."""
    pages = [[{"i": n}] for n in range(20)]
    _fake_oura(pages, monkeypatch)
    r = client.fetch("heartrate", "2026-08-01T00:00:00Z", "2026-08-02T00:00:00Z",
                        page_limit=3)
    assert r["pages"] == 3
    # These records carry no `day`, so there is no day to name — the message
    # falls back to asking for a narrower range.
    assert "truncated" in r and "narrow the range" in r["truncated"]
    assert "continue_from" not in r, "nothing to continue from without a day"


def test_a_single_page_asks_for_no_more(monkeypatch):
    llamadas = _fake_oura([[{"i": 1}]], monkeypatch)
    r = client.fetch("daily_sleep", "2026-08-01", "2026-08-02")
    assert r["n"] == 1 and r["pages"] == 1
    assert len(llamadas) == 1


# ── The date range: the second scar ────────────────────────────────────────
# Measured against the real API on 2026-08-09. `end_date` is INCONSISTENT across
# collections — daily_activity, sleep and workout lose the last day requested;
# the others do not — and on top of that `workout` filters by UTC date while
# reporting `day` in local time, so at -06:00 an evening workout counted on the
# following day. Asking for [d..d] returned ZERO records with no warning at all:
# the same family of failure as not paginating.
def test_requests_two_extra_days_on_each_side(monkeypatch):
    """Not a courtesy margin: `workout` is exclusive AND skewed to UTC, and the two
    stack. One day was not enough."""
    urls = []
    _fake_oura([[{}]], monkeypatch, registrar=urls)
    client.fetch("daily_sleep", "2026-08-10", "2026-08-20")
    assert "start_date=2026-08-08" in urls[-1]
    assert "end_date=2026-08-22" in urls[-1]


def test_the_datetime_range_is_not_widened(monkeypatch):
    """`heartrate` is requested with a time. Shifting it two days would ask for a
    thousand times more samples than needed to fix a problem it doesn't have."""
    urls = []
    _fake_oura([[{}]], monkeypatch, registrar=urls)
    client.fetch("heartrate", "2026-08-10T00:00:00Z", "2026-08-10T06:00:00Z")
    assert "start_datetime=2026-08-10T00%3A00%3A00Z" in urls[-1]


def test_trims_the_extra_days_and_says_so(monkeypatch):
    """The extra day was requested on purpose; dropping it silently would leave
    whoever reads the response unable to tell "there is no data" from "we removed
    it"."""
    pagina = [{"day": d} for d in ("2026-08-08", "2026-08-09", "2026-08-10",
                                   "2026-08-11", "2026-08-12")]
    _fake_oura([pagina], monkeypatch)
    r = client.fetch("daily_sleep", "2026-08-09", "2026-08-11")
    assert [x["day"] for x in r["data"]] == ["2026-08-09", "2026-08-10", "2026-08-11"]
    assert r["n"] == 3
    assert r["discarded_out_of_range"] == 2


def test_a_single_day_returns_that_day(monkeypatch):
    """The case that was broken: asking for [d..d] returned zero on daily_activity,
    sleep and workout."""
    pagina = [{"day": "2026-08-09"}, {"day": "2026-08-10"}, {"day": "2026-08-11"}]
    _fake_oura([pagina], monkeypatch)
    r = client.fetch("workout", "2026-08-10", "2026-08-10")
    assert r["n"] == 1 and r["data"][0]["day"] == "2026-08-10"


def test_the_day_comes_from_start_day_when_there_is_no_day(monkeypatch):
    """`rest_mode_period` and `enhanced_tag` carry no `day`: they carry `start_day`."""
    pagina = [{"start_day": "2026-08-09"}, {"start_day": "2026-08-30"}]
    _fake_oura([pagina], monkeypatch)
    r = client.fetch("enhanced_tag", "2026-08-09", "2026-08-09")
    assert r["n"] == 1


def test_what_cannot_be_dated_is_kept(monkeypatch):
    """Discarding what you do not understand is the fastest way to under-deliver,
    which is exactly what this package exists not to do."""
    pagina = [{"day": "2026-08-09"}, {"sin_fecha": True}, {"day": "2026-09-30"}]
    _fake_oura([pagina], monkeypatch)
    r = client.fetch("daily_sleep", "2026-08-09", "2026-08-09")
    assert r["n"] == 2
    assert {"sin_fecha": True} in r["data"]


def test_dia_de_reconoce_las_claves_con_hora():
    assert client.day_of({"timestamp": "2026-08-09T12:00:00-06:00"}) == "2026-08-09"
    assert client.day_of({"bedtime_start": "2026-08-09T23:10:00-06:00"}) == "2026-08-09"
    assert client.day_of({"nada": 1}) is None
    assert client.day_of("no es un dict") is None


def test_truncating_leaves_a_cursor_to_continue_from(monkeypatch):
    """`truncated` warned but didn't let you continue: whoever received it could
    only retry blind.

    And then it pointed at something unusable. `continue_from` was Oura's
    `next_token`, and no parameter accepts a token back — deliberately, because
    a cursor parameter hands pagination to the model, which is the failure this
    package exists to prevent. The response told the model to continue from a
    value it had nowhere to put.

    It is the last day actually reached, which works with `start`.
    """
    pages = [[{"day": f"2026-01-{d:02d}", "score": 70}] for d in range(1, 21)]
    _fake_oura(pages, monkeypatch)
    r = client.fetch("daily_sleep", "2026-01-01", "2026-12-31", page_limit=3)
    assert r["continue_from"] == "2026-01-03"
    assert "start" in r["truncated"]
    assert "next_token" not in str(r), "the opaque token must not leak"


# ── CSV: el mismo dato sin repetir las claves 37,000 veces ──────────────────
def test_the_header_comes_from_the_union_not_the_first_record(monkeypatch):
    """Taking the header from the first record is the easiest way to lose data
    here: one record with an extra field is enough for that field to vanish
    without a trace."""
    _fake_oura([[{"day": "2026-08-10", "score": 1},
                  {"day": "2026-08-11", "score": 2, "extra": 9}]], monkeypatch)
    r = client.fetch("daily_sleep", "2026-08-10", "2026-08-11", format="csv")
    assert "extra" in r["columns"]
    assert "9" in r["data"]


def test_avisa_cuando_los_registros_no_traen_las_mismas_claves(monkeypatch):
    """An empty cell can be an absent field or a null value. With records of
    differing shape the difference matters, and hiding it feigns regularity."""
    _fake_oura([[{"day": "2026-08-10"}, {"day": "2026-08-11", "extra": 1}]], monkeypatch)
    r = client.fetch("daily_sleep", "2026-08-10", "2026-08-11", format="csv")
    assert "uneven_columns" in r
    _fake_oura([[{"day": "2026-08-10"}, {"day": "2026-08-11"}]], monkeypatch)
    r = client.fetch("daily_sleep", "2026-08-10", "2026-08-11", format="csv")
    assert "uneven_columns" not in r


def test_lo_anidado_va_como_json_en_su_celda(monkeypatch):
    """Flattening would invent columns Oura does not have; omitting would lose data."""
    _fake_oura([[{"day": "2026-08-10", "contributors": {"deep": 91}}]], monkeypatch)
    r = client.fetch("daily_sleep", "2026-08-10", "2026-08-10", format="csv")
    assert '{""deep"":91}' in r["data"]


def test_the_date_is_the_first_column(monkeypatch):
    """Es la columna con la que se cruza contra otra fuente."""
    _fake_oura([[{"score": 1, "day": "2026-08-10", "aaa": 2}]], monkeypatch)
    r = client.fetch("daily_sleep", "2026-08-10", "2026-08-10", format="csv")
    assert r["columns"][0] == "day"


def test_the_csv_arrives_when_truncated_too(monkeypatch):
    """Con dos salidas, la truncada se iba sin format ni avisos — y es la que
    it is precisely the response that most needs everything it says believed."""
    pages = [[{"day": "2026-08-10", "i": n}] for n in range(20)]
    _fake_oura(pages, monkeypatch)
    r = client.fetch("daily_sleep", "2026-08-10", "2026-08-10",
                        format="csv", page_limit=3)
    assert r["format"] == "csv" and "truncated" in r
    assert r["continue_from"] == "2026-08-10"


# ── The 429: a bounded retry ───────────────────────────────────────────────
# Oura sends NO rate-limit headers on successful responses — verified 2026-08-09
# — so a client cannot know how close it is to the ceiling. It only finds out
# once it has been refused, and by then it may have 30 pages fetched that would
# be thrown away.
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

    monkeypatch.setattr(client.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(client.time, "sleep", dormidas.append)
    monkeypatch.setenv("OURA_PAT", "x")
    return estado


def test_retries_the_429_and_gets_through(monkeypatch):
    dormidas = []
    _falla_n_veces(monkeypatch, 2, dormidas=dormidas)
    assert client.fetch("personal_info")["n"] == 1
    assert dormidas == [1.0, 2.0]          # backoff exponencial


def test_a_persistent_429_gives_up_having_said_everything(monkeypatch):
    _falla_n_veces(monkeypatch, 99)
    with pytest.raises(client.OuraError, match="2 retries"):
        client.fetch("personal_info")


def test_honors_retry_after_in_seconds(monkeypatch):
    cab = email.message.Message()
    cab["Retry-After"] = "3"
    dormidas = []
    _falla_n_veces(monkeypatch, 1, cabeceras=cab, dormidas=dormidas)
    client.fetch("personal_info")
    assert dormidas == [3.0]


def test_retry_after_cannot_hang_the_conversation(monkeypatch):
    """Una cabecera que pida media hora no puede dejar esperando a nadie."""
    cab = email.message.Message()
    cab["Retry-After"] = "1800"
    dormidas = []
    _falla_n_veces(monkeypatch, 1, cabeceras=cab, dormidas=dormidas)
    client.fetch("personal_info")
    assert dormidas == [client.MAX_WAIT]


def test_only_the_429_is_retried(monkeypatch):
    """A 401 does not improve by waiting: retrying it only takes three times as long
    to deliver the same bad news."""
    intentos = {"n": 0}

    def urlopen(req, timeout=None):
        intentos["n"] += 1
        raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized",
                                     email.message.Message(), None)

    monkeypatch.setattr(client.urllib.request, "urlopen", urlopen)
    monkeypatch.setenv("OURA_PAT", "x")
    with pytest.raises(client.OuraError, match="401"):
        client.fetch("personal_info")
    assert intentos["n"] == 1


# ── `fields` y `latest`: los dos que Oura ignora en silencio ────────────────
# Measured against the API on 2026-08-09. Both fail the same way: no error, just
# more than asked for. `fields=made_up` returns the COMPLETE record — the
# projection never happens — and `latest=true` on a collection that does not
# support it returns the entire collection. The asker believes they filtered and
# did not.
def test_los_campos_van_como_fields(monkeypatch):
    urls = []
    _fake_oura([[{"day": "2026-08-10", "score": 1}]], monkeypatch, registrar=urls)
    client.fetch("daily_sleep", "2026-08-10", "2026-08-10", fields=["score", "day"])
    assert "fields=score%2Cday" in urls[-1]


def test_avisa_de_los_campos_que_no_aparecieron(monkeypatch):
    _fake_oura([[{"day": "2026-08-10", "score": 1}]], monkeypatch)
    r = client.fetch("daily_sleep", "2026-08-10", "2026-08-10",
                        fields=["score", "no_existe"])
    assert r["ignored_fields"] == ["no_existe"]


def test_sin_campos_pedidos_no_hay_aviso(monkeypatch):
    _fake_oura([[{"day": "2026-08-10"}]], monkeypatch)
    r = client.fetch("daily_sleep", "2026-08-10", "2026-08-10")
    assert "ignored_fields" not in r


def test_ultimo_solo_donde_oura_lo_respeta(monkeypatch):
    urls = []
    _fake_oura([[{"bpm": 60}]], monkeypatch, registrar=urls)
    client.fetch("heartrate", latest=True)
    assert "latest=true" in urls[-1]


def test_ultimo_se_rechaza_donde_oura_lo_ignora(monkeypatch):
    """Rejected HERE rather than letting Oura return the whole collection: asking
    for the latest record and receiving ten while believing it is one is worse
    than an error."""
    _fake_oura([[{}]], monkeypatch)
    with pytest.raises(client.OuraError, match="it's ignored"):
        client.fetch("daily_sleep", "2026-08-01", "2026-08-10", latest=True)


def test_ultimo_no_exige_rango(monkeypatch):
    """`latest` needs no dates, and demanding them would invent a requirement."""
    _fake_oura([[{"bpm": 60}]], monkeypatch)
    assert client.fetch("ring_battery_level", latest=True)["n"] == 1


# ── The sandbox: trying it with nothing to authenticate with ───────────────
# Oura deprecated personal tokens in December 2025. Anyone arriving today has no
# way to get one, so "install it and then get a token" stopped being a path. The
# sandbox is official — it is in the OpenAPI spec, with 34 mirror routes — and it
# accepts any string as Authorization.
def test_the_sandbox_asks_for_no_token(monkeypatch):
    monkeypatch.delenv("OURA_PAT", raising=False)
    monkeypatch.delenv("OURA_PAT_FILE", raising=False)
    monkeypatch.setenv("OURA_SANDBOX", "1")
    assert client._token().reveal() == "sandbox"


def test_the_sandbox_changes_the_base(monkeypatch):
    monkeypatch.setenv("OURA_SANDBOX", "1")
    assert client.base().endswith("/v2/sandbox/usercollection")
    monkeypatch.setenv("OURA_SANDBOX", "0")
    assert client.base().endswith("/v2/usercollection")


def test_the_base_can_be_forced(monkeypatch):
    """`OURA_API_BASE_URL` wins over everything: it is what allows pointing at a
    double in a test without monkeypatching the module."""
    monkeypatch.setenv("OURA_SANDBOX", "1")
    monkeypatch.setenv("OURA_API_BASE_URL", "http://localhost:9999/v2/x/")
    assert client.base() == "http://localhost:9999/v2/x"


def test_apagado_el_sandbox_vuelven_a_hacer_falta_credenciales(monkeypatch, tmp_path):
    monkeypatch.delenv("OURA_PAT", raising=False)
    monkeypatch.delenv("OURA_PAT_FILE", raising=False)
    monkeypatch.delenv("OURA_SANDBOX", raising=False)
    monkeypatch.setenv("OURA_CREDENTIALS", str(tmp_path / "no-existe.json"))
    monkeypatch.setenv("OURA_NO_KEYCHAIN", "1")
    with pytest.raises(client.OuraError, match="no credentials"):
        client._token()


# ── Parameters ─────────────────────────────────────────────────────────────
def test_date_collections_require_a_range(monkeypatch):
    monkeypatch.setenv("OURA_PAT", "x")
    with pytest.raises(client.OuraError, match="needs start and end"):
        client.fetch("daily_sleep")


def test_cada_forma_manda_el_parametro_que_le_toca(monkeypatch):
    """`daily_*` uses start_date; `heartrate` uses start_datetime. Sending the wrong
    one returns a 400 that then has to be deciphered."""
    urls = []
    _fake_oura([[{}]], monkeypatch, registrar=urls)
    client.fetch("daily_sleep", "2026-08-01", "2026-08-02")
    assert "start_date=" in urls[-1] and "start_datetime=" not in urls[-1]
    client.fetch("heartrate", "2026-08-01T00:00:00Z", "2026-08-02T00:00:00Z")
    assert "start_datetime=" in urls[-1]
    client.fetch("personal_info")
    assert "?" not in urls[-1]      # with no range, no parameters are invented


def test_sin_credenciales_se_ofrecen_los_tres_caminos(monkeypatch, tmp_path):
    """The message pointed at the personal-tokens page, and since December 2025
    that page issues none: whoever landed there got stuck without knowing why.
    Now the first option is the one that works."""
    monkeypatch.delenv("OURA_PAT", raising=False)
    monkeypatch.delenv("OURA_PAT_FILE", raising=False)
    monkeypatch.delenv("OURA_SANDBOX", raising=False)
    monkeypatch.setenv("OURA_CREDENTIALS", str(tmp_path / "no-existe.json"))
    monkeypatch.setenv("OURA_NO_KEYCHAIN", "1")
    with pytest.raises(client.OuraError) as exc:
        client.fetch("personal_info")
    mensaje = str(exc.value)
    assert "OURA_SANDBOX=1" in mensaje          # the one with no paperwork, first
    assert "--authorize" in mensaje
    assert "December 2025" in mensaje       # why the PAT is no longer an option


# ── Garbage input: the error should say what to do ─────────────────────────
def test_the_backwards_range_is_caught_here(monkeypatch):
    """Caught before hitting the network because the EXTRA_DAYS margin changes the
    dates: Oura would return a 400 quoting two dates the asker never wrote, and
    diagnosing that costs more than the error itself."""
    _fake_oura([[{}]], monkeypatch)
    with pytest.raises(client.OuraError, match="runs backwards"):
        client.fetch("daily_sleep", "2026-08-10", "2026-08-01")


def test_the_range_error_quotes_the_dates_that_were_written(monkeypatch):
    _fake_oura([[{}]], monkeypatch)
    with pytest.raises(client.OuraError) as exc:
        client.fetch("daily_sleep", "2026-08-10", "2026-08-01")
    assert "2026-08-10" in str(exc.value) and "2026-08-01" in str(exc.value)
    assert "2026-08-08" not in str(exc.value)      # la de adentro, no


def test_ouras_422_is_translated_into_something_readable(monkeypatch):
    """Oura contesta `detail` como el arreglo de errores de pydantic, cuyo JSON
    runs past 200 characters before reaching the only thing that matters. Trimmed
    raw it left `{"detail":[{"type":"datetime_from_date_pars` and nothing else."""
    cuerpo = json.dumps({"detail": [{
        "type": "datetime_from_date_parsing",
        "loc": ["query", "start_date", "datetime"],
        "msg": "Input should be a valid datetime or date",
        "input": "ayer"}]}).encode()

    def urlopen(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 422, "Unprocessable",
                                     email.message.Message(), io.BytesIO(cuerpo))

    monkeypatch.setattr(client.urllib.request, "urlopen", urlopen)
    monkeypatch.setenv("OURA_PAT", "x")
    with pytest.raises(client.OuraError) as exc:
        client.fetch("daily_sleep", "2026-08-01", "2026-08-01")
    m = str(exc.value)
    assert "start_date" in m
    assert "valid datetime" in m
    assert "'ayer'" in m                    # what was received, which is what one looks for
    assert "datetime_from_date_parsing" not in m   # el ruido, fuera


def test_the_string_form_of_detail_is_read_too(monkeypatch):
    cuerpo = json.dumps({"detail": "Start time is greater than end time"}).encode()

    def urlopen(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 400, "Bad Request",
                                     email.message.Message(), io.BytesIO(cuerpo))

    monkeypatch.setattr(client.urllib.request, "urlopen", urlopen)
    monkeypatch.setenv("OURA_PAT", "x")
    with pytest.raises(client.OuraError, match="Start time is greater"):
        client.fetch("personal_info")


def test_an_unreadable_error_body_breaks_nothing(monkeypatch):
    def urlopen(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 500, "Server Error",
                                     email.message.Message(), io.BytesIO(b"<html>"))

    monkeypatch.setattr(client.urllib.request, "urlopen", urlopen)
    monkeypatch.setenv("OURA_PAT", "x")
    with pytest.raises(client.OuraError, match="500"):
        client.fetch("personal_info")


# ── `day`: the most common query shouldn't require writing a range ─────────
def test_dia_equivale_a_inicio_igual_a_fin(monkeypatch):
    _fake_oura([[{"day": "2026-08-09"}, {"day": "2026-08-10"}]], monkeypatch)
    from oura_mcp.server import oura_query
    f = getattr(oura_query, "fn", oura_query)
    r = f(collection="workout", day="2026-08-10")
    assert r["n"] == 1 and r["data"][0]["day"] == "2026-08-10"


def test_dia_y_rango_juntos_es_un_error(monkeypatch):
    """Mixing the two has no obvious interpretation, and choosing one silently is
    how wrong ranges slip through."""
    _fake_oura([[{}]], monkeypatch)
    from oura_mcp.server import oura_query
    f = getattr(oura_query, "fn", oura_query)
    assert "not both" in f(collection="workout", day="2026-08-10",
                           start="2026-08-01")["error"]


# ── Annotations: what the MCP client needs to know without asking ──────────
def test_all_three_declare_themselves_read_only():
    """No es una promesa: no hay un POST, ni un PUT, ni un DELETE en todo el
    paquete. Declararlo evita que el client confirme en cada llamada, y el
    directorio de conectores de Claude lo exige."""
    import asyncio
    from oura_mcp.server import server
    tools = asyncio.run(server.list_tools())
    assert len(tools) == 3
    for t in tools:
        assert t.title, t.name
        assert t.annotations.read_only_hint is True, t.name
        assert t.annotations.destructive_hint is False, t.name
        # Los data vienen de un servicio externo: la misma llamada dos veces
        # can differ if the ring synced in between. Saying otherwise would
        # invite someone to memoize the response.
        assert t.annotations.open_world_hint is True, t.name


def test_there_is_not_a_single_write_in_the_package():
    """The read-only annotation has to stay true when someone adds code. This test
    is the one that finds out."""
    import pathlib
    raiz = pathlib.Path(__file__).parent.parent / "src" / "oura_mcp"
    for file in raiz.glob("*.py"):
        texto = file.read_text(encoding="utf-8")
        for verbo in ('"POST"', "'POST'", '"PUT"', "'PUT'", '"DELETE"', "'DELETE'",
                      '"PATCH"', "'PATCH'"):
            assert verbo not in texto, f"{file.name} trae {verbo}"


# ── Nothing may carry the token away ───────────────────────────────────────
def test_the_token_is_not_printed_by_accident():
    """Un str con el token adentro sale solo por demasiados lados: el repr de las
    locals in a traceback, a debug print that was left behind, an f-string
    written in a hurry. It already cost a token once here."""
    s = client.Secret("abcdefghij")
    assert "abcdefghij" not in repr(s)
    assert "abcdefghij" not in str(s)
    assert "abcdefghij" not in f"{s}"
    assert "abcdefghij" not in "{}".format(s)
    assert "10" in repr(s)              # the length yes, which is what diagnoses
    assert s.reveal() == "abcdefghij"  # revealing it is explicit and greppable


def test_el_secreto_sabe_cuanto_mide():
    """`--check` reporta la longitud del token, nunca el token."""
    assert len(client.Secret("abc")) == 3



def test_the_error_never_carries_the_token(monkeypatch):
    """Error messages are what gets copied and pasted most. The token travels in a
    header and has no business ever leaving it."""
    monkeypatch.setenv("OURA_PAT", "token-secretisimo-12345")

    def revienta(req, timeout=None):
        raise client.urllib.error.HTTPError(req.full_url, 401, "no", {}, None)

    monkeypatch.setattr(client.urllib.request, "urlopen", revienta)
    with pytest.raises(client.OuraError) as e:
        client.fetch("personal_info")
    assert "token-secretisimo-12345" not in str(e.value)


def test_revisar_reporta_el_largo_del_token_no_el_token(monkeypatch):
    from oura_mcp import server
    monkeypatch.setenv("OURA_PAT", "token-secretisimo-12345")
    monkeypatch.setattr(server, "fetch",
                        lambda *a, **k: {"data": [{"age": 39, "email": "x@y.z"}]})
    r = server.check()
    texto = json.dumps(r)
    assert "token-secretisimo-12345" not in texto
    assert r["token_length"] == len("token-secretisimo-12345")
    # And from the response only the field NAMES, never the values.
    assert r["profile_fields"] == ["age", "email"]
    assert "x@y.z" not in texto and "39" not in texto


def test_the_token_can_come_from_a_file(monkeypatch, tmp_path):
    """An MCP server is registered in a config JSON, and putting the token there
    leaves it in the clear in a file that gets backed up, synced, and shared when
    asking for help."""
    f = tmp_path / "pat"
    f.write_text("token-from-file\n")
    monkeypatch.delenv("OURA_PAT", raising=False)
    monkeypatch.setenv("OURA_PAT_FILE", str(f))
    assert client._token().reveal() == "token-from-file"


def test_the_file_wins_over_the_variable(monkeypatch, tmp_path):
    f = tmp_path / "pat"
    f.write_text("del-file")
    monkeypatch.setenv("OURA_PAT", "de-la-variable")
    monkeypatch.setenv("OURA_PAT_FILE", str(f))
    assert client._token().reveal() == "del-file"


def test_an_empty_file_does_not_pass_as_a_token(monkeypatch, tmp_path):
    f = tmp_path / "pat"
    f.write_text("   \n")
    monkeypatch.delenv("OURA_PAT", raising=False)
    monkeypatch.setenv("OURA_PAT_FILE", str(f))
    with pytest.raises(client.OuraError, match="empty file"):
        client._token()


# ── The loop's third exit: a repeated `next_token` ─────────────────────────
def test_un_next_token_repetido_se_detecta_como_ciclo(monkeypatch):
    """It would be ironic to carry this here. Without detecting it the client made
    50 identical requests, returned 50 copies of the same record, and the warning
    said "shorten the range" — useless advice, because shortening does not stop
    the API from repeating itself. It also burned 49 requests against a rate
    limit Oura announces in no header."""
    llamadas = []

    def urlopen(req, timeout=None):
        llamadas.append(req.full_url)
        return _RespuestaFalsa(json.dumps(
            {"data": [{"day": "2026-08-01"}], "next_token": "SIEMPRE-EL-MISMO"}
        ).encode())

    monkeypatch.setattr(client.urllib.request, "urlopen", urlopen)
    monkeypatch.setenv("OURA_PAT", "x")
    r = client.fetch("daily_sleep", "2026-08-01", "2026-08-01")
    assert len(llamadas) == 2, f"hizo {len(llamadas)} peticiones"
    assert "pagination_cycle" in r
    assert "truncated" not in r, "not truncation: the API is misbehaving"


def test_el_ciclo_no_estorba_a_la_paginacion_normal(monkeypatch):
    """Distinct tokens on each page run their course to the end."""
    pages = [[{"i": n}] for n in range(6)]
    _fake_oura(pages, monkeypatch)
    r = client.fetch("heartrate", "2026-08-01T00:00:00Z", "2026-08-02T00:00:00Z")
    assert r["n"] == 6 and r["pages"] == 6
    assert "pagination_cycle" not in r


# ── Response shapes Oura shouldn't send, but just in case ──────────────────
def test_data_that_is_not_a_list_is_reported(monkeypatch):
    """Wrapping the whole envelope would turn that into "one record" shaped like
    `{"data": …}` that looks legitimate. Staying quiet about it would be the
    usual failure, committed by us."""
    def urlopen(req, timeout=None):
        return _RespuestaFalsa(json.dumps({"data": {"day": "2026-08-01"}}).encode())

    monkeypatch.setattr(client.urllib.request, "urlopen", urlopen)
    monkeypatch.setenv("OURA_PAT", "x")
    with pytest.raises(client.OuraError, match="no interpretation is being invented"):
        client.fetch("daily_sleep", "2026-08-01", "2026-08-01")


def test_las_colecciones_sin_sobre_siguen_funcionando(monkeypatch):
    """`personal_info` and `ring_configuration` are not wrapped in `data`: the whole
    body is the record. It is told apart by the ABSENCE of the key."""
    def urlopen(req, timeout=None):
        return _RespuestaFalsa(json.dumps({"email": "x", "age": 1}).encode())

    monkeypatch.setattr(client.urllib.request, "urlopen", urlopen)
    monkeypatch.setenv("OURA_PAT", "x")
    r = client.fetch("personal_info")
    assert r["n"] == 1 and r["data"][0]["age"] == 1


def test_an_empty_response_is_zero_records_not_one(monkeypatch):
    def urlopen(req, timeout=None):
        return _RespuestaFalsa(b"{}")

    monkeypatch.setattr(client.urllib.request, "urlopen", urlopen)
    monkeypatch.setenv("OURA_PAT", "x")
    assert client.fetch("personal_info")["n"] == 0


# ── Response size, which nobody was looking at ─────────────────────────────
def test_an_enormous_response_comments_on_itself(monkeypatch):
    """Measured: 30 days of `daily_activity` is 252,000 characters, and 87% of it is
    a single field (`met`, a per-minute MET series). A server handing over a
    quarter of a million characters without comment spends the asker's context on
    data they probably did not want."""
    gordo = {"day": "2026-08-01", "score": 80, "met": list(range(6000))}
    _fake_oura([[dict(gordo, day=f"2026-08-{d:02d}") for d in range(1, 6)]], monkeypatch)
    r = client.fetch("daily_activity", "2026-08-01", "2026-08-05")
    aviso = r["large_response"]
    assert aviso["heaviest_field"] == "met"
    assert aviso["percentage"] > 90
    assert "fields" in aviso["suggestion"]


def test_nothing_is_trimmed_on_its_own_initiative(monkeypatch):
    """The warning does NOT come with a trim. Cutting without being asked would be
    under-delivering, which is precisely what this package exists not to do."""
    gordo = {"day": "2026-08-01", "met": list(range(6000))}
    _fake_oura([[dict(gordo, day=f"2026-08-{d:02d}") for d in range(1, 6)]], monkeypatch)
    r = client.fetch("daily_activity", "2026-08-01", "2026-08-05")
    assert r["n"] == 5
    assert all(len(x["met"]) == 6000 for x in r["data"])


def test_si_ya_eligio_columnas_no_se_le_insiste(monkeypatch):
    gordo = {"day": "2026-08-01", "met": list(range(6000))}
    _fake_oura([[dict(gordo, day=f"2026-08-{d:02d}") for d in range(1, 6)]], monkeypatch)
    r = client.fetch("daily_activity", "2026-08-01", "2026-08-05", fields=["met"])
    assert "large_response" not in r


def test_una_respuesta_normal_no_lleva_aviso(monkeypatch):
    _fake_oura([[{"day": "2026-08-01", "score": 80}]], monkeypatch)
    r = client.fetch("daily_sleep", "2026-08-01", "2026-08-01")
    assert "large_response" not in r


# ── `n: 0`: the most common answer to the most common questions ────────────
def test_an_empty_query_explains_what_is_known(monkeypatch):
    """"how did I sleep last night?" and "am I recovered?" often return n=0, and
    that does not distinguish between not wearing the ring, it not having synced,
    a future date, or a missing permission. A model receiving `{"n": 0}` will
    answer "you did not sleep" with complete confidence, and may be wrong."""
    _fake_oura([[]], monkeypatch)
    r = client.fetch("daily_sleep", "2026-01-01", "2026-01-02")
    assert "empty" in r
    assert "you didn't sleep" in r["empty"]["do_not_confuse"]


def test_a_future_range_is_reported(monkeypatch):
    import datetime
    manana = (datetime.date.today() + datetime.timedelta(days=30)).isoformat()
    _fake_oura([[]], monkeypatch)
    r = client.fetch("daily_sleep", manana, manana)
    assert any("future" in x for x in r["empty"]["what_we_know"])


def test_asking_up_to_today_warns_about_syncing(monkeypatch):
    """The number-one cause of a legitimate empty result: the ring has not synced."""
    import datetime
    hoy = datetime.date.today().isoformat()
    _fake_oura([[]], monkeypatch)
    r = client.fetch("daily_sleep", hoy, hoy)
    assert any("syncs" in x for x in r["empty"]["what_we_know"])


def test_si_hay_datos_no_se_explica_nada(monkeypatch):
    _fake_oura([[{"day": "2026-01-01"}]], monkeypatch)
    assert "empty" not in client.fetch("daily_sleep", "2026-01-01", "2026-01-01")


def test_toda_coleccion_declara_su_alcance():
    """Sirve para distinguir «no hay dato» de «no diste ese permiso»: las dos se
    identical (n=0) and lead to opposite conclusions."""
    from oura_mcp.collections import SCOPE_OF, COLLECTIONS
    assert set(SCOPE_OF) == set(COLLECTIONS)
    from oura_mcp.credentials import SCOPES
    assert set(SCOPE_OF.values()) <= set(SCOPES)


def test_the_instructions_carry_what_cannot_be_guessed():
    """They travel in every session: only what changes an answer goes in."""
    from oura_mcp.server import server
    ins = server.instructions
    for imprescindible in ("n: 0", "truncated", "continue_from", "start_datetime",
                           "large_response", "fields"):
        assert imprescindible in ins, imprescindible


# ── The sandbox as the first experience of someone who just installed ──────
def test_the_profile_in_sandbox_explains_instead_of_returning_404(monkeypatch):
    """The sandbox answers a bare 404 for `personal_info`. A "404: Not Found"
    to someone who has just installed says the server is broken, when what is
    actually happening is that Oura publishes no fake data for the one collection
    carrying email, age, weight and height."""
    monkeypatch.setenv("OURA_SANDBOX", "1")
    with pytest.raises(client.OuraError) as exc:
        client.fetch("personal_info")
    m = str(exc.value)
    assert "does not exist in Oura's sandbox" in m
    assert "Everything else works here" in m       # so it does not look like all failed
    assert "--authorize" in m                     # and where to go next


def test_outside_the_sandbox_the_profile_is_requested_normally(monkeypatch):
    monkeypatch.delenv("OURA_SANDBOX", raising=False)
    _fake_oura([[{"email": "x"}]], monkeypatch)
    assert client.fetch("personal_info")["n"] == 1


def test_only_personal_info_is_missing_from_the_sandbox():
    """Si Oura agrega o quita alguna, el job semanal de deriva lo dice."""
    from oura_mcp.collections import COLLECTIONS, WITHOUT_SANDBOX
    assert WITHOUT_SANDBOX == {"personal_info"}
    assert WITHOUT_SANDBOX <= set(COLLECTIONS)



def test_a_recovered_429_says_so_in_the_response(monkeypatch):
    """A retry that SUCCEEDS used to leave no trace at all.

    The caller waited, the answer came back clean, and nothing said Oura had
    refused. The data is correct, so this isn't the same bug as the four this
    package was built for — but being throttled is a fact about the NEXT query,
    not this one. A model that doesn't know it was just refused will happily ask
    for another fifty pages, and that is the request that fails.
    """
    dormidas = []
    _falla_n_veces(monkeypatch, 2, dormidas=dormidas)
    r = client.fetch("daily_sleep", "2026-01-01", "2026-01-02")

    assert r["n"] == 1, "the data still arrives complete"
    aviso = r["rate_limited"]
    assert "429" in aviso
    assert "complete" in aviso, "it must not read as though data were lost"
    assert "smaller" in aviso or "wait" in aviso, "it has to say what to do next"


def test_a_clean_request_carries_no_rate_limit_notice(monkeypatch):
    """Otherwise it rides on every answer and stops being read."""
    _fake_oura([[{"i": 1}]], monkeypatch)
    r = client.fetch("daily_sleep", "2026-01-01", "2026-01-02")
    assert "rate_limited" not in r
