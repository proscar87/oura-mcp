"""`oura_compare`: is the difference between two periods larger than the noise?

THE TOOL THIS REPOSITORY SAID IT WOULD NEVER SHIP, and the condition it ships
under is this file. The objection was never to arithmetic: it was that "your
HRV is up 12%" reaches a model as a number without its method, and across nine
years of real data three out of four day-to-day changes are the metric's own
swing. So every answer here carries the band the metric moves in on its own,
and the default reading of a difference is «within noise».

THE CALIBRATION IS THE SPECIFICATION. The method was not chosen and then
tested; it was chosen BY these simulations. Daily Oura metrics are
autocorrelated — a good night tends to follow a good night — so seven days are
worth fewer than seven independent observations, and a textbook standard error
calls noise a change roughly a third of the time (measured: 34–38% at ρ=0.65).
Estimating that autocorrelation from the two short periods themselves is biased
low and still gave 11–21%. Estimated from the person's own preceding 120 days,
with a t critical value, it stays at or under 5% at every autocorrelation
tried. Those are the numbers the tests below hold it to.

None of it touches the network.
"""

import math
import random

import pytest

from oura_mcp import method as M


def _ar1(n, rho, rng):
    x = [rng.gauss(0, 1) / math.sqrt(1 - rho * rho)]
    for _ in range(n - 1):
        x.append(rho * x[-1] + rng.gauss(0, 1))
    return x


def _days(start_ordinal, values):
    import datetime as dt
    return [(dt.date.fromordinal(start_ordinal + i).isoformat(), v)
            for i, v in enumerate(values)]


BASE = 739000                  # an arbitrary ordinal; only consecutiveness matters


def _run(values_h, values_a, values_b, gap=10):
    h = _days(BASE, values_h)
    a = _days(BASE + len(values_h), values_a)
    b = _days(BASE + len(values_h) + len(values_a) + gap, values_b)
    return M.compare_series(a, b, h)


def _false_positive_rate(rho, n, reps, seed, history=120):
    rng = random.Random(seed)
    hits = 0
    for _ in range(reps):
        s = _ar1(history + 2 * n + 10, rho, rng)
        r = _run(s[:history], s[history:history + n], s[history + n + 10:])
        hits += r["verdict"] == "outside_noise"
    return hits / reps


# ── The calibration: what makes this tool honest ──────────────────────────
@pytest.mark.parametrize("rho,n", [(0.0, 7), (0.0, 14), (0.3, 14), (0.65, 7),
                                   (0.65, 14), (0.8, 21)])
def test_noise_is_called_noise_at_most_about_one_time_in_twenty(rho, n):
    """Two periods drawn from the SAME process: any «outside_noise» is a false
    alarm. The ceiling is 7%, not 5%, to leave room for simulation error at
    1,500 repetitions (±1.1% at 5%) — not for the method."""
    assert _false_positive_rate(rho, n, reps=1500, seed=int(rho * 100) + n) <= 0.07


def test_a_real_change_is_seen():
    """A calibration that never says «outside» would pass the test above by
    being useless. A shift of three standard deviations, two weeks each side,
    mild autocorrelation: it has to be seen nearly every time."""
    rng = random.Random(7)
    seen = 0
    for _ in range(300):
        s = _ar1(120 + 38, 0.3, rng)
        sd = 1 / math.sqrt(1 - 0.09)
        b = [v + 3 * sd for v in s[134:148]]
        seen += _run(s[:120], s[120:134], b)["verdict"] == "outside_noise"
    assert seen / 300 >= 0.9


# ── When it cannot know, it says so ─────────────────────────────────────────
def test_without_enough_history_there_is_no_verdict():
    """How much this metric swings on its own is estimated from the person's
    history. Without 60 days of it there is no honest band — and a guessed one
    is the manufactured signal this tool exists not to produce."""
    rng = random.Random(1)
    s = _ar1(40 + 28, 0.5, rng)
    r = _run(s[:40], s[40:54], s[54:68], gap=0)
    assert r["verdict"] == "cannot_tell"
    assert "60" in r["reading"]
    assert "noise_band" not in r


def test_too_few_days_in_a_period_is_no_verdict():
    rng = random.Random(2)
    s = _ar1(120 + 20, 0.5, rng)
    r = _run(s[:120], s[120:125], s[125:139])
    assert r["verdict"] == "cannot_tell"
    assert "7" in r["reading"]


def test_every_verdict_says_what_it_could_not_have_seen():
    """«within noise» read as «no change» is the misreading that matters most.
    The band is also the smallest difference these days could have told apart,
    and the reading has to say so in words."""
    rng = random.Random(3)
    s = _ar1(120 + 38, 0.6, rng)
    r = _run(s[:120], s[120:134], s[144:158], gap=0)
    assert r["verdict"] == "within_noise"
    assert "could not" in r["reading"]
    assert r["noise_band"] > 0


# ── The autocorrelation estimate ────────────────────────────────────────────
def test_a_gap_in_the_days_breaks_the_pair():
    """Lag-1 means consecutive CALENDAR days. A missing night must not make
    Monday's value the neighbour of Wednesday's."""
    days = [("2026-01-01", 1.0), ("2026-01-02", 2.0), ("2026-01-04", 1.0),
            ("2026-01-05", 2.0)]
    pairs = M.consecutive_pairs(days)
    assert pairs == [(1.0, 2.0), (1.0, 2.0)]


def test_negative_autocorrelation_is_not_credited():
    """Clamped at zero. A negative estimate would widen n beyond the number of
    days — claiming more certainty than independent days could give."""
    alternating = [1.0, -1.0] * 60
    h = _days(BASE, alternating)
    assert M.lag1(h) == 0.0


# ── The one rule that is a choice, stated where it is made ─────────────────
def test_sleep_uses_the_main_sleep_and_says_so():
    """`sleep` has one record per sleep, naps included. Averaging a nap with
    the night is a method decision, so it is made once, here, and named in the
    response: the longest `long_sleep` of each day. A day with only naps has no
    value, and is counted."""
    records = [
        {"day": "2026-01-01", "type": "long_sleep", "total_sleep_duration": 25000, "average_hrv": 40},
        {"day": "2026-01-01", "type": "late_nap", "total_sleep_duration": 1800, "average_hrv": 90},
        {"day": "2026-01-02", "type": "long_sleep", "total_sleep_duration": 20000, "average_hrv": 50},
        {"day": "2026-01-02", "type": "long_sleep", "total_sleep_duration": 26000, "average_hrv": 44},
        {"day": "2026-01-03", "type": "sleep", "total_sleep_duration": 3000, "average_hrv": 70},
    ]
    s = M.series(records, "sleep", "average_hrv")
    assert s["values"] == [("2026-01-01", 40.0), ("2026-01-02", 44.0)]
    assert s["without_main_sleep"] == 1


def test_a_missing_value_is_dropped_and_counted():
    records = [{"day": "2026-01-01", "score": 80}, {"day": "2026-01-02", "score": None},
               {"day": "2026-01-03", "contributors": {}}]
    s = M.series(records, "daily_readiness", "score")
    assert s["values"] == [("2026-01-01", 80.0)]
    assert s["missing_values"] == 2


def test_a_nested_field_is_reachable():
    records = [{"day": "2026-01-01", "contributors": {"hrv_balance": 71}}]
    assert M.series(records, "daily_readiness", "contributors.hrv_balance")["values"] == \
        [("2026-01-01", 71.0)]


# ── The tool: refusals and pass-throughs ────────────────────────────────────
def test_a_collection_with_many_records_a_day_is_refused():
    """`heartrate` is a sample every few minutes. «The mean of period A» there
    is a different question with its own method, not this one."""
    r = M.check_metric("heartrate.bpm")
    assert r and "one record per day" in r


def test_a_metric_needs_a_collection_and_a_field():
    assert "collection.field" in M.check_metric("score")
    assert M.check_metric("daily_readiness.score") is None
    assert M.check_metric("sleep.average_hrv") is None


def test_the_tool_excludes_today_and_says_so(monkeypatch):
    """Today's `daily_activity` is still accumulating steps: including it drags
    the recent period down with a number that is not finished."""
    from oura_mcp import server as S
    monkeypatch.setattr(S, "_today", lambda: "2026-03-31")
    captured = {}

    def fake_fetch(collection, start, end, **kw):
        captured.update(collection=collection, start=start, end=end, fields=kw.get("fields"))
        return {"collection": collection, "n": 0, "data": []}

    monkeypatch.setattr(S, "fetch", fake_fetch)
    fn = getattr(S.oura_compare, "fn", S.oura_compare)
    r = fn(metric="daily_activity.steps", a_start="2026-03-01", a_end="2026-03-14",
           b_start="2026-03-18", b_end="2026-03-31")
    assert r["period_b"]["end"] == "2026-03-30"
    assert "today" in r["excluded"]
    assert captured["end"] == "2026-03-30"
    assert captured["fields"] == ["steps"]


def test_the_tool_refuses_a_truncated_fetch(monkeypatch):
    from oura_mcp import server as S
    monkeypatch.setattr(S, "_today", lambda: "2026-06-01")
    monkeypatch.setattr(S, "fetch", lambda *a, **k: {"n": 5, "data": [], "truncated": "x"})
    fn = getattr(S.oura_compare, "fn", S.oura_compare)
    r = fn(metric="daily_readiness.score", a_start="2026-03-01", a_end="2026-03-14",
           b_start="2026-03-18", b_end="2026-03-31")
    assert "error" in r and "incomplete" in r["error"]


def test_sample_data_is_marked_on_the_statistics_too(monkeypatch):
    """Statistics computed on Oura's synthetic data are still synthetic, and a
    band around made-up numbers reads as authoritative. The marker travels."""
    from oura_mcp import server as S
    monkeypatch.setattr(S, "_today", lambda: "2026-06-01")
    rng = random.Random(4)
    import datetime as dt
    start = dt.date(2025, 11, 1)
    data = [{"day": (start + dt.timedelta(days=i)).isoformat(), "score": 70 + 5 * v}
            for i, v in enumerate(_ar1(160, 0.4, rng))]
    monkeypatch.setattr(S, "fetch", lambda *a, **k: {"n": len(data), "data": data,
                                                     "synthetic": "sample"})
    fn = getattr(S.oura_compare, "fn", S.oura_compare)
    r = fn(metric="daily_readiness.score", a_start="2026-03-01", a_end="2026-03-14",
           b_start="2026-03-18", b_end="2026-03-31")
    assert r["synthetic"] == "sample"
    assert r["verdict"] in ("within_noise", "outside_noise")


def test_overlapping_periods_are_refused():
    from oura_mcp import server as S
    fn = getattr(S.oura_compare, "fn", S.oura_compare)
    r = fn(metric="daily_readiness.score", a_start="2026-03-01", a_end="2026-03-14",
           b_start="2026-03-10", b_end="2026-03-20")
    assert "overlap" in r["error"]


def test_a_metric_that_never_varies_has_no_band_to_measure():
    """Found by calling the tool on Oura's sandbox, whose `score` is 80 every
    day: the band came out ±0 and the reading said «a real change smaller than
    0 could not have been seen» — a sentence shaped like a method with nothing
    inside it. No variation means no noise was measured, so no verdict."""
    r = _run([80.0] * 120, [80.0] * 14, [80.0] * 14)
    assert r["verdict"] == "cannot_tell"
    assert "did not vary" in r["reading"]
    assert "noise_band" not in r
