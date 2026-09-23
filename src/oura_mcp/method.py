"""The method behind `oura_compare`, as plain functions over plain numbers.

WHY IT IS SEPARATE, AND WHY IT IS WRITTEN LIKE THIS. The same arithmetic runs
in TypeScript (`ts/src/method.ts`), and the two must agree to the last printed
digit. `statistics.mean` sums with exact fractions and JavaScript sums floats,
so they would not. Every loop here is a plain float loop in the same order as
its TypeScript twin; the parity test feeds both the same series.

THE QUESTION IT ANSWERS is narrower than it looks: is the difference between
two periods' means larger than what this metric does ON ITS OWN over periods
that long? Not why, not whether it will last, not whether it matters. The
method, and why each piece is there, measured rather than assumed:

- Daily metrics are AUTOCORRELATED — a good night tends to follow a good night
  — so seven days carry less than seven days' worth of evidence. The standard
  error uses an effective number of days, `n(1-ρ)/(1+ρ)`. Without it, noise is
  called a change about a third of the time at ρ=0.65.
- ρ is estimated from the person's OWN PRECEDING 120 DAYS, not from the two
  periods. From seven or fourteen days the estimate is biased low, and the
  band came out too narrow: 11–21% false alarms instead of 5%.
- A t critical value on Welch's degrees of freedom, not 1.96. With a handful
  of effective days, z overstates certainty (13% false alarms at n=7).
- Negative ρ is clamped to zero: crediting it would claim more certainty than
  independent days could give.

Held to all of that by `tests/test_compare.py`, which simulates it.
"""

from __future__ import annotations

import datetime
import decimal
import math

MIN_DAYS = 7
MIN_HISTORY = 60
# Consecutive-day pairs in the history. With the estimator normalized per pair,
# the simulated false-alarm rate stays at about 5% with half the days missing
# once there are 20; with none — worn every other day — there is nothing to
# estimate the day-to-day dependence from, which is not «no dependence».
MIN_PAIRS = 20
HISTORY_DAYS = 120
RHO_CEILING = 0.95

# One record per day, or `sleep` with the main-sleep rule below. Everything else
# is many records a day, where «the mean of a period» is a different question.
DAILY = ("daily_sleep", "daily_readiness", "daily_activity", "daily_stress",
         "daily_spo2", "daily_resilience", "daily_cardiovascular_age", "vO2_max",
         "sleep")

MAIN_SLEEP_RULE = (
    "`sleep` has one record per sleep, naps included. Each day's value is its "
    "longest `long_sleep`; a day with only naps or rests has no value.")

MULTIPLE_COMPARISONS = (
    "This is one comparison. Asking many — other metrics, other periods — and "
    "keeping whichever crosses the band will find a crossing by chance about "
    "one time in twenty.")

# Two-sided 95% critical values of Student's t, by degrees of freedom. A table
# rather than a function because neither standard library has one, and the two
# implementations must use the same numbers.
_T95 = (12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228,
        2.201, 2.179, 2.160, 2.145, 2.131, 2.120, 2.110, 2.101, 2.093, 2.086,
        2.080, 2.074, 2.069, 2.064, 2.060, 2.056, 2.052, 2.048, 2.045, 2.042)


def t_critical(df: float) -> float:
    """Rounded DOWN to a whole degree of freedom: the conservative side."""
    d = max(1, int(df))
    if d <= 30:
        return _T95[d - 1]
    if d <= 40:
        return 2.021
    if d <= 60:
        return 2.000
    if d <= 120:
        return 1.980
    return 1.960


def check_metric(metric: str) -> str | None:
    """The reason `metric` cannot be compared, or None if it can."""
    if "." not in metric:
        return (f"`metric` is `collection.field`, like `daily_readiness.score` or "
                f"`sleep.average_hrv`; got «{metric}»")
    collection = metric.split(".", 1)[0]
    if collection not in DAILY:
        return (f"`{collection}` does not have one record per day, and a period's "
                f"mean there is a different question. Comparable: "
                f"{', '.join(DAILY)}")
    return None


def _get(record: dict, path: str):
    v = record
    for part in path.split("."):
        if not isinstance(v, dict):
            return None
        v = v.get(part)
    return v


def series(records: list, collection: str, field: str) -> dict:
    """One value per day, sorted, with what was left out counted."""
    missing = non_numeric = 0
    picked: dict[str, dict] = {}
    without_main = set()
    if collection == "sleep":
        for r in records:
            day = r.get("day")
            if not day:
                continue
            if r.get("type") != "long_sleep":
                without_main.add(day)
                continue
            best = picked.get(day)
            if best is None or (r.get("total_sleep_duration") or 0) > \
                    (best.get("total_sleep_duration") or 0):
                picked[day] = r
        without_main -= set(picked)
    else:
        for r in records:
            if r.get("day"):
                picked[r["day"]] = r

    values = []
    for day in sorted(picked):
        v = _get(picked[day], field)
        if v is None:
            missing += 1
        elif isinstance(v, bool) or not isinstance(v, (int, float)):
            non_numeric += 1
        else:
            values.append((day, float(v)))
    # Not `out`: this is internal, and `out[...]` is what the surface guard reads
    # as a response key.
    found = {"values": values, "missing_values": missing, "non_numeric": non_numeric}
    if collection == "sleep":
        found["without_main_sleep"] = len(without_main)
    return found


def _ordinal(day: str) -> int:
    return datetime.date.fromisoformat(day).toordinal()


def consecutive_pairs(days: list) -> list:
    """(value, next value) for each pair of CALENDAR-consecutive days."""
    pairs = []
    for (d0, v0), (d1, v1) in zip(days, days[1:]):
        if _ordinal(d1) - _ordinal(d0) == 1:
            pairs.append((v0, v1))
    return pairs


def _mean(xs: list) -> float:
    s = 0.0
    for x in xs:
        s += x
    return s / len(xs)


def _variance(xs: list, m: float) -> float:
    s = 0.0
    for x in xs:
        s += (x - m) * (x - m)
    return s / (len(xs) - 1)


def _median(xs: list) -> float:
    s = sorted(xs)
    k = len(s) // 2
    return s[k] if len(s) % 2 else (s[k - 1] + s[k]) / 2


def lag1(days: list) -> float:
    """Lag-1 autocorrelation over consecutive days, clamped to [0, 0.95]."""
    vals = [v for _, v in days]
    if len(vals) < 3:
        return 0.0
    m = _mean(vals)
    den = 0.0
    for v in vals:
        den += (v - m) * (v - m)
    pairs = consecutive_pairs(days)
    num = 0.0
    for a, b in pairs:
        num += (a - m) * (b - m)
    if den == 0.0 or not pairs:
        return 0.0
    # EACH SUM OVER ITS OWN COUNT. The cross-products exist only where two
    # consecutive days both have a value; the squares exist for every value.
    # Dividing one sum by the other shrank ρ in proportion to the missing days
    # — about half its size at 30% missing — and the false alarms crept back.
    return min(max((num / len(pairs)) / (den / len(vals)), 0.0), RHO_CEILING)


def _fixed(x: float, places: int) -> str:
    """`x` to `places` decimals, ties AWAY FROM ZERO — what JavaScript's
    `toFixed` does. Python's own formatting rounds ties to even, so the mean of
    sixteen whole numbers ending in .0625 printed 1.062 here and 1.063 in the
    bundle: the same answer, differently, depending on the install."""
    q = decimal.Decimal(1).scaleb(-places)
    return str(decimal.Decimal(x).quantize(q, rounding=decimal.ROUND_HALF_UP))


def _r(x: float, places: int = 3) -> float:
    return float(_fixed(x, places))


def _num(x: float) -> str:
    """Three decimals, trailing zeros dropped. The same in both languages."""
    s = _fixed(x, 3)
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def _signed(x: float) -> str:
    s = _num(x)
    return s if s.startswith("-") or s == "0" else "+" + s


def compare_series(a: list, b: list, history: list) -> dict:
    """Period A against period B, against the person's own history."""
    out = {"period_a": {"n": len(a)}, "period_b": {"n": len(b)}}
    if len(a) < MIN_DAYS or len(b) < MIN_DAYS:
        out["verdict"] = "cannot_tell"
        out["reading"] = (
            f"Each period needs at least {MIN_DAYS} days with a value; these have "
            f"{len(a)} and {len(b)}. Fewer days than that cannot be told apart from "
            f"an ordinary week.")
        return out
    if len(history) < MIN_HISTORY:
        out["verdict"] = "cannot_tell"
        out["reading"] = (
            f"How much this metric moves on its own is measured from the "
            f"{HISTORY_DAYS} days before the first period, and needs at least "
            f"{MIN_HISTORY} with a value; there are {len(history)}. Without it any "
            f"band would be a guess, and a guessed band is exactly the signal "
            f"this tool exists not to invent.")
        return out

    n_pairs = len(consecutive_pairs(history))
    if n_pairs < MIN_PAIRS:
        out["verdict"] = "cannot_tell"
        out["reading"] = (
            f"The history has too few consecutive days with a value — {n_pairs}, "
            f"and at least {MIN_PAIRS} are needed — to measure how much one day "
            f"depends on the day before. Treating that as «no dependence» would "
            f"narrow the band and call noise a change.")
        return out

    rho = lag1(history)
    va = [v for _, v in a]
    vb = [v for _, v in b]
    ma, mb = _mean(va), _mean(vb)
    shrink = (1 - rho) / (1 + rho)
    na, nb = len(va) * shrink, len(vb) * shrink
    sa, sb = _variance(va, ma) / na, _variance(vb, mb) / nb
    se = math.sqrt(sa + sb)
    hv = [v for _, v in history]
    if se == 0.0 or _variance(hv, _mean(hv)) == 0.0:
        # Found on Oura's sandbox, whose score is 80 every day: the band came
        # out ±0 and the reading promised a method with nothing inside it.
        out["verdict"] = "cannot_tell"
        out["reading"] = (
            "This metric did not vary at all in these days or in the history, so "
            "there is no noise to measure a difference against. Constant values "
            "are what sample data and a disconnected ring produce.")
        return out
    df = (sa + sb) * (sa + sb) / (sa * sa / max(na - 1, 1e-9) + sb * sb / max(nb - 1, 1e-9))
    t = t_critical(df)
    band = t * se
    diff = mb - ma

    swings = [abs(y - x) for x, y in consecutive_pairs(history)]
    out["period_a"]["mean"] = _r(ma)
    out["period_b"]["mean"] = _r(mb)
    out["difference"] = _r(diff)
    out["noise_band"] = _r(band)
    if abs(diff) > band:
        out["verdict"] = "outside_noise"
        out["reading"] = (
            f"The difference ({_signed(diff)}) is larger than what this metric does "
            f"on its own over periods this long (±{_num(band)}), at 95% confidence. "
            f"It says the level differs between the two periods — not why, and not "
            f"that it will last.")
    else:
        out["verdict"] = "within_noise"
        out["reading"] = (
            f"The difference ({_signed(diff)}) is inside what this metric does on "
            f"its own over periods this long (±{_num(band)}). It is not evidence of "
            f"a change — and with these days, a real change smaller than "
            f"{_num(band)} would be missed more often than seen.")
    out["typical_daily_change"] = _r(_median(swings)) if swings else None
    out["method"] = {
        "autocorrelation": _r(rho),
        "estimated_from_days": len(history),
        "effective_days": {"a": _r(na, 1), "b": _r(nb, 1)},
        "t_critical": t,
        "confidence": 0.95,
    }
    out["multiple_comparisons"] = MULTIPLE_COMPARISONS
    return out
