"""`oura_relate`: do two metrics move together more than unrelated ones would?

CORRELATION HAS MORE WAYS TO LIE THAN A DIFFERENCE OF MEANS, and each one got a
simulated null before the method existed. Measured on the prototype, false
alarms at 95% confidence when each safeguard is removed:

    no weekday means removed     41–93%   two metrics sharing a weekly rhythm
    no differencing                 58%   two metrics sharing a slow trend
    no autocorrelation correction  ≤12%   differenced noise is anti-correlated
    no cost for the weekday means  ≤13%   fourteen fitted means are not free

With all four, every null tried stays at about 5% (measured up to 5.2%). What
it measures is narrower than «are these related»: whether their DAY-TO-DAY
CHANGES move together, once each weekday's usual level is taken out. Not
levels, not cause, not direction.

None of it touches the network.
"""

import datetime as dt
import math
import random

import pytest

from oura_mcp import method as M

BASE = 739000


def _ar1(n, rho, rng):
    x = [rng.gauss(0, 1) / math.sqrt(1 - rho * rho)]
    for _ in range(n - 1):
        x.append(rho * x[-1] + rng.gauss(0, 1))
    return x


def _days(values, keep=None):
    return [(dt.date.fromordinal(BASE + i).isoformat(), v)
            for i, v in enumerate(values) if keep is None or keep[i]]


def _weekend(values, amp):
    return [v + (amp if dt.date.fromordinal(BASE + i).weekday() >= 5 else 0.0)
            for i, v in enumerate(values)]


def _null(kind, n, rng, gaps=0.0):
    if kind == "white":
        x, y = [rng.gauss(0, 1) for _ in range(n)], [rng.gauss(0, 1) for _ in range(n)]
    elif kind == "weekly":
        x, y = _weekend(_ar1(n, 0.65, rng), 1.5), _weekend(_ar1(n, 0.65, rng), 1.5)
    elif kind == "walk":
        x, y = [0.0], [0.0]
        for _ in range(n - 1):
            x.append(x[-1] + rng.gauss(0, 1))
            y.append(y[-1] + rng.gauss(0, 1))
    elif kind == "trend":
        x = [0.05 * i + v for i, v in enumerate(_ar1(n, 0.5, rng))]
        y = [0.05 * i + v for i, v in enumerate(_ar1(n, 0.5, rng))]
    else:
        raise ValueError(kind)
    keep = [rng.random() >= gaps for _ in range(n)]      # shared: no ring, no data
    return _days(x, keep), _days(y, keep)


def _false_alarms(kind, n, reps, seed, gaps=0.0, lag=0):
    rng = random.Random(seed)
    hits = told = 0
    for _ in range(reps):
        x, y = _null(kind, n, rng, gaps)
        r = M.relate_series(x, y, lag)
        if r["verdict"] != "cannot_tell":
            told += 1
            hits += r["verdict"] == "outside_noise"
    return hits / max(told, 1), told / reps


# ── The nulls: unrelated metrics must read as unrelated ────────────────────
@pytest.mark.parametrize("kind,n", [("white", 90), ("weekly", 90), ("weekly", 180),
                                    ("walk", 90), ("trend", 120)])
def test_unrelated_metrics_are_not_called_related(kind, n):
    rate, answered = _false_alarms(kind, n, reps=1200, seed=sum(map(ord, kind)) + n)   # not hash(): salted per process
    assert answered > 0.8
    assert rate <= 0.07, f"{kind}: {rate:.3f}"


def test_nor_with_days_missing():
    rate, answered = _false_alarms("weekly", 180, reps=1000, seed=3, gaps=0.3)
    assert answered > 0.5
    assert rate <= 0.07


def test_nor_at_a_lag():
    rate, _ = _false_alarms("weekly", 120, reps=1000, seed=4, lag=1)
    assert rate <= 0.07


# ── A real relation is seen ─────────────────────────────────────────────────
def test_a_real_next_day_relation_is_seen():
    """y the day after depends on x: the case «does a hard training day lower
    the next morning's readiness». Moderate effect, three months."""
    rng = random.Random(8)
    seen = 0
    for _ in range(300):
        x = _ar1(121, 0.5, rng)
        e = _ar1(121, 0.5, rng)
        y = [e[i] + (0.5 * x[i - 1] if i else 0.0) for i in range(121)]
        r = M.relate_series(_days(x), _days(y), 1)
        seen += r["verdict"] == "outside_noise"
    assert seen / 300 >= 0.8


# ── When it cannot know ─────────────────────────────────────────────────────
def test_a_month_is_too_short_and_says_how_long_is_enough():
    rng = random.Random(1)
    x, y = _null("white", 30, rng)
    r = M.relate_series(x, y, 0)
    assert r["verdict"] == "cannot_tell"
    assert "effective" in r["reading"]
    assert "correlation" not in r


def test_a_metric_that_never_varies_relates_to_nothing():
    rng = random.Random(2)
    x = _days([rng.gauss(0, 1) for _ in range(120)])
    y = _days([80.0] * 120)
    assert M.relate_series(x, y, 0)["verdict"] == "cannot_tell"


# ── The alignment is visible ────────────────────────────────────────────────
def test_the_first_pair_shows_which_day_met_which():
    """Oura files last night's sleep under the morning it ended, and activity
    under the day it happened. Which night follows which day is the caller's
    call — `lag` — and the response shows the first pair it formed so a wrong
    alignment is visible instead of silent."""
    rng = random.Random(5)
    x = _days([rng.gauss(0, 1) for _ in range(120)])
    y = _days([rng.gauss(0, 1) for _ in range(120)])
    r = M.relate_series(x, y, 1)
    first = r["first_pair"]
    gap = (dt.date.fromisoformat(first["y_day"]) - dt.date.fromisoformat(first["x_day"])).days
    assert gap == 1


def test_it_warns_about_neighbouring_lags_and_many_tries():
    rng = random.Random(6)
    x = _days([rng.gauss(0, 1) for _ in range(120)])
    y = _days([rng.gauss(0, 1) for _ in range(120)])
    r = M.relate_series(x, y, 0)
    assert "one in twenty" in r["multiple_comparisons"]
    assert "cause" in r["reading"]


# ── The tool ─────────────────────────────────────────────────────────────────
def test_the_tool_fetches_each_metric_once_and_leaves_today_out(monkeypatch):
    from oura_mcp import server as S
    monkeypatch.setattr(S, "_today", lambda: "2026-06-01")
    calls = []

    def fake_fetch(collection, start, end, **kw):
        calls.append((collection, start, end, kw.get("fields")))
        return {"n": 0, "data": []}

    monkeypatch.setattr(S, "fetch", fake_fetch)
    fn = getattr(S.oura_relate, "fn", S.oura_relate)
    r = fn(x="daily_activity.high_activity_time", y="daily_readiness.score",
           start="2026-02-01", end="2026-06-01", lag=1)
    assert r["verdict"] == "cannot_tell"
    assert "today" in r["excluded"]
    # y reaches `lag` days past x so the last x day keeps its partner — but
    # never past yesterday.
    assert calls == [("daily_activity", "2026-02-01", "2026-05-31", ["high_activity_time"]),
                     ("daily_readiness", "2026-02-01", "2026-05-31", ["score"])]


def test_the_tool_refuses_a_lag_it_cannot_honour():
    from oura_mcp import server as S
    fn = getattr(S.oura_relate, "fn", S.oura_relate)
    r = fn(x="daily_sleep.score", y="daily_readiness.score",
           start="2026-01-01", end="2026-04-01", lag=30)
    assert "lag" in r["error"]


def test_the_same_metric_against_itself_is_refused():
    from oura_mcp import server as S
    fn = getattr(S.oura_relate, "fn", S.oura_relate)
    r = fn(x="daily_sleep.score", y="daily_sleep.score",
           start="2026-01-01", end="2026-04-01", lag=0)
    assert "itself" in r["error"]


def test_a_change_across_a_missing_day_is_not_a_day_to_day_change():
    """Monday to Wednesday is two days of change, not one. The nulls tolerate
    it — it adds noise, not bias — so they cannot guard it; this does."""
    series = {BASE: 1.0, BASE + 1: 3.0, BASE + 3: 10.0, BASE + 4: 11.0}
    assert M._changes(series) == {BASE + 1: 2.0, BASE + 4: 1.0}
