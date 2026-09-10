"""`oura_today`, and the line it is not allowed to cross.

WHY A FOURTH TOOL AT ALL. «How did I sleep?» is the most common question there
is, and answering it well needs today's two records plus enough history to know
whether they are unusual. Through `oura_query` that is four round trips and four
chances to stop early. This is one.

WHY IT STILL COMPUTES NOTHING. `server.py` states that no average and no trend
is computed here, `llms.txt` says an average computed inside arrives without its
method, and the directory submission says the same. A 7-day delta — which is
what the competing Go server returns — would make all three false. So the days
come back RAW and the comparison happens where the method can be cited. The
tests below are mostly about that: aggregation is the failure mode, not a
missing feature.
"""

import datetime

import pytest

from oura_mcp import client, server

from test_oura_mcp import _fake_oura


def _tool():
    fn = server.oura_today
    return getattr(fn, "fn", fn)


AYER = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()


# ── What it returns ────────────────────────────────────────────────────────
def test_one_call_reaches_both_collections(monkeypatch):
    """The point of the tool, as a request count: sleep and readiness in one."""
    llamadas = _fake_oura([[{"day": AYER, "score": 71}]], monkeypatch)
    r = _tool()(days=7)
    assert "sleep" in r and "readiness" in r
    assert len(llamadas) == 2
    assert any("daily_sleep" in u for u in llamadas)
    assert any("daily_readiness" in u for u in llamadas)


def test_the_records_come_back_whole(monkeypatch):
    """Raw, not summarised. Whatever Oura sent is what the model reads."""
    registro = {"day": AYER, "score": 71, "contributors": {"deep_sleep": 88}}
    _fake_oura([[registro]], monkeypatch)
    r = _tool()(days=7)
    assert r["sleep"]["records"][0]["contributors"] == {"deep_sleep": 88}


# ── The line ───────────────────────────────────────────────────────────────
def test_it_computes_no_average_and_says_so(monkeypatch):
    """THE WHOLE REASON THIS TOOL IS ALLOWED TO EXIST. The moment it returns an
    average, a delta or a trend, three published statements become false: the
    module docstring, `llms.txt`, and the long description in `SUBMISSION.md`.

    Asserted as an absence AND as a statement: the response says out loud that
    nothing was computed, because a caller must be able to tell a composition
    from an analysis without reading the source."""
    _fake_oura([[{"day": AYER, "score": 71}, {"day": AYER, "score": 60}]],
               monkeypatch)
    r = _tool()(days=7)
    # Everything EXCEPT the disclaimer, which legitimately contains the words
    # «average», «delta» and «trend» in order to deny them. Scanning it too is
    # how the first version of this test failed on the sentence promising the
    # thing it was checking for.
    plano = repr({k: v for k, v in r.items() if k != "computed"}).lower()
    for prohibido in ("average", "mean", "delta", "trend", "baseline",
                      "vs_", "change_", "percent"):
        assert prohibido not in plano, f"it computed something: {prohibido}"
    assert "computed no average" in r["computed"]


def test_no_numeric_key_is_invented(monkeypatch):
    """The keys are the ones Oura sent plus the ones this file declares. A
    computed number hiding under a plausible name is the failure that matters,
    and it would not be caught by looking for the word «average»."""
    _fake_oura([[{"day": AYER, "score": 71}]], monkeypatch)
    r = _tool()(days=7)
    permitidas = {"today", "days", "computed", "sleep", "readiness", "missing"}
    assert set(r) <= permitidas, f"unexpected top-level key: {set(r) - permitidas}"
    for clave in ("sleep", "readiness"):
        assert set(r[clave]) <= {"n", "records", "empty", "truncated",
                                 "pagination_cycle", "synthetic", "cached",
                                 "rate_limited", "large_response", "error"}


# ── What it refuses, and what it survives ──────────────────────────────────
@pytest.mark.parametrize("dias", [0, -1, 31, 1000])
def test_an_out_of_range_window_is_refused_not_clamped(dias, monkeypatch):
    """Clamping answers a question nobody asked, and the answer looks exactly
    like one to the question that was asked. Same family as everything else
    this package refuses."""
    _fake_oura([[{"day": AYER}]], monkeypatch)
    r = _tool()(days=dias)
    assert "error" in r and "sleep" not in r


def test_an_empty_day_is_named_not_silently_dropped(monkeypatch):
    """`n: 0` does not mean the person did not sleep. The ring syncs when it
    likes and the current day is the one most often missing — which is the
    first of Oura's four silent failures, arriving through a new door."""
    _fake_oura([[]], monkeypatch)
    r = _tool()(days=7)
    assert "missing" in r
    assert "sleep" in r["missing"] and "readiness" in r["missing"]
    assert "NOT" in r["missing"]


def test_one_collection_failing_does_not_lose_the_other(monkeypatch):
    """A 403 on readiness is no reason to withhold the sleep that arrived."""
    real = client.fetch

    def falla_una(collection, *a, **k):
        if collection == "daily_readiness":
            raise client.OuraError("Oura refused `daily_readiness` with 403")
        return real(collection, *a, **k)

    _fake_oura([[{"day": AYER, "score": 71}]], monkeypatch)
    monkeypatch.setattr(server, "fetch", falla_una)
    r = _tool()(days=7)
    assert r["sleep"]["n"] == 1
    assert "403" in r["readiness"]["error"]
    assert "readiness" in r["missing"]


def test_the_warnings_survive_the_wrapper(monkeypatch):
    """`synthetic` is the one that matters most: a wrapper that drops it hands
    Oura's sample data to a model with nothing marking it, which is this
    package's own thesis committed by a convenience function."""
    monkeypatch.setenv("OURA_SANDBOX", "1")
    _fake_oura([[{"day": AYER, "score": 71}]], monkeypatch)
    r = _tool()(days=7)
    assert "synthetic" in r["sleep"]
