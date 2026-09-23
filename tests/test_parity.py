"""The two implementations must answer the same question the same way.

WHY THIS FILE EXISTS. Differential testing between Python and TypeScript has
been the single highest-yield technique in this repository: `rate_limited`
missing on one side, `date_range` vs `dateRange` in the catalog, a lone carriage
return unquoted in one CSV and not the other, milliseconds printed as seconds,
a version constant two releases stale. Every one was found by asking the same
question twice and comparing.

Most of them were found by hand. These are the comparisons worth keeping.

IT NEVER TOUCHES THE NETWORK. Both sides are handed the same literal data.

It skips itself if Node or the compiled `ts/dist` is missing, because the
mandatory CI runs Python only and a parity test that fails for lack of a
toolchain teaches nobody anything.
"""

import json
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).parent.parent
DIST = ROOT / "ts" / "dist" / "client.js"

pytestmark = pytest.mark.skipif(
    not (shutil.which("node") and DIST.exists()),
    reason="needs node and a compiled ts/dist (run `cd ts && npx tsc`)",
)


def _node(expr: str, datos) -> str:
    """Evaluate `expr` in TypeScript with `d` bound to the given records."""
    guion = (
        f'import {{ sizeWarning, toCsv, shiftDays, dayOf, rangeHasClosed }} '
        f'from "{DIST}";\n'
        'const d = JSON.parse(await new Promise(r => {'
        "  let s = ''; process.stdin.on('data', c => s += c);"
        "  process.stdin.on('end', () => r(s)); }));\n"
        f"console.log(JSON.stringify({expr}));"
    )
    r = subprocess.run(["node", "--input-type=module", "-e", guion],
                       input=json.dumps(datos), capture_output=True, text=True,
                       timeout=60)
    assert r.returncode == 0, r.stderr[:400]
    return r.stdout.strip()


def test_the_size_warning_counts_the_same_characters():
    """TypeScript summed the VALUES only — no keys, no quotes, no punctuation —
    and undercounted by roughly half, so a response of 60,000 characters warned
    in Python and passed in silence there. Python then counted with the default
    `, ` and `: ` separators, which nobody transmits. Both count the record, the
    way it goes over the wire."""
    from oura_mcp.client import _size_warning

    datos = [{"day": f"2026-01-{d:02d}", "met": "x" * 2200, "score": 70}
             for d in range(1, 29)]
    py = _size_warning(datos, None)
    ts = json.loads(_node("sizeWarning(d, undefined)", datos))

    assert py is not None and ts is not None, "one of them stopped warning"
    assert py["characters"] == ts["characters"], (py["characters"], ts["characters"])


@pytest.mark.parametrize("valor", [
    "ran 5k, felt great", 'they said "excellent"', "line1\nline2", "a\rb", '"',
])
def test_the_csv_escapes_identically(valor):
    """A lone carriage return went unquoted on one side and not the other, which
    shifts every column after it for readers that end a row on a bare `\\r`."""
    from oura_mcp.client import to_csv

    datos = [{"day": "2026-01-01", "comment": valor, "score": 73}]
    py, _, _ = to_csv(datos)
    ts = json.loads(_node("toCsv(d).text", datos))
    assert py == ts


@pytest.mark.parametrize("fecha", ["2026-01-01", "2024-02-29", "2026-12-31"])
def test_the_date_shift_agrees(fecha):
    from oura_mcp.client import _shift_days
    for dias in (-2, 2):
        ts = json.loads(_node(f"shiftDays({json.dumps(fecha)}, {dias})", []))
        assert _shift_days(fecha, dias) == ts, (fecha, dias)


@pytest.mark.parametrize("fecha", ["2026-02-29", "2026-06-31", "2026-13-01"])
def test_both_refuse_the_same_impossible_dates(fecha):
    """One rolled them over into a different month and answered «no records»."""
    from oura_mcp.client import OuraError, _shift_days

    with pytest.raises(OuraError):
        _shift_days(fecha, -2)

    r = subprocess.run(
        ["node", "--input-type=module", "-e",
         f'import {{ shiftDays }} from "{DIST}";\n'
         f'try {{ shiftDays({json.dumps(fecha)}, -2); console.log("ACEPTADA"); }}\n'
         f'catch (e) {{ console.log("rechazada"); }}'],
        capture_output=True, text=True, timeout=60)
    assert r.stdout.strip() == "rechazada", f"TypeScript accepted {fecha}"


@pytest.mark.parametrize("registro,esperado", [
    ({"day": "2026-01-05"}, "2026-01-05"),
    ({"start_day": "2026-01-05"}, "2026-01-05"),
    ({"timestamp": "2026-01-05T23:30:00-06:00"}, "2026-01-05"),
    ({"nada": 1}, None),
])
def test_the_day_of_a_record_agrees(registro, esperado):
    """Whose day a record belongs to decides what the trim keeps. Disagreeing
    here means the two return different records for the same query."""
    from oura_mcp.client import day_of

    assert day_of(registro) == esperado
    assert json.loads(_node("dayOf(d[0]) ?? null", [registro])) == esperado


@pytest.mark.parametrize("dias_atras", [-1, 0, 1, 2, 400])
def test_the_calendar_rule_agrees(dias_atras):
    """WHETHER A DAY HAS CLOSED IS THE WHOLE CACHE. Disagreeing here means one
    implementation holds an answer the other refuses to hold — and the one that
    holds it wrong serves a day that could still gain records as if it were
    settled, which is the failure this package exists to refuse.

    -1 is tomorrow, 0 is today, and both must be refused. The boundary is the
    only interesting part: `<` and `<=` differ on exactly one day, and it is the
    day the ring is still syncing.
    """
    import datetime

    from oura_mcp.client import _range_has_closed

    fecha = (datetime.date.today() - datetime.timedelta(days=dias_atras)).isoformat()
    esperado = _range_has_closed(fecha)
    obtenido = json.loads(_node(f'rangeHasClosed("{fecha}")', []))
    assert obtenido == esperado, f"{fecha}: python={esperado} typescript={obtenido}"


# ── oura_compare: the one computed answer, computed the same way ──────────
METHOD = ROOT / "ts" / "dist" / "method.js"


def _compare_cases():
    import datetime as dt
    import math
    import random
    rng = random.Random(11)
    cases = []

    def ar1(n, rho):
        x = [rng.gauss(0, 1) / math.sqrt(1 - rho * rho)]
        for _ in range(n - 1):
            x.append(rho * x[-1] + rng.gauss(0, 1))
        return x

    def days(start, vals):
        d0 = dt.date(2026, 1, 1).toordinal() + start
        return [[dt.date.fromordinal(d0 + i).isoformat(), v] for i, v in enumerate(vals)]

    for rho, n, shift in ((0.0, 7, 0), (0.4, 14, 0), (0.65, 21, 2.5), (0.8, 10, -3)):
        s = ar1(120 + 2 * n + 5, rho)
        b = [v + shift for v in s[125 + n:]]
        cases.append((days(0, s[:120]), days(120, s[120:120 + n]), days(125 + n, b)))
    # Whole numbers over sixteen days: means that end in .0625, the rounding
    # tie where Python and JavaScript disagree unless one copies the other.
    whole = [float(rng.randint(5000, 12000)) for _ in range(152)]
    cases.append((days(0, whole[:120]), days(120, whole[120:136]), days(136, whole[136:152])))
    # A metric that never varies, as Oura's sandbox serves it.
    cases.append((days(0, [80.0] * 120), days(120, [80.0] * 14), days(134, [80.0] * 14)))
    # Not enough history, and not enough days: the two «cannot_tell» paths.
    s = ar1(90, 0.5)
    cases.append((days(0, s[:40]), days(40, s[40:54]), days(54, s[54:68])))
    cases.append((days(0, s[:70]), days(70, s[70:75]), days(75, s[75:90])))
    return cases


@pytest.mark.skipif(not METHOD.exists(), reason="needs ts/dist/method.js")
def test_compare_gives_the_same_answer_in_both():
    from oura_mcp import method as M
    cases = _compare_cases()
    guion = (
        f'import {{ compareSeries }} from "{METHOD}";\n'
        'const cs = JSON.parse(await new Promise(r => {'
        "  let s = ''; process.stdin.on('data', c => s += c);"
        "  process.stdin.on('end', () => r(s)); }));\n"
        "console.log(JSON.stringify(cs.map(([h, a, b]) => compareSeries(a, b, h))));"
    )
    r = subprocess.run(["node", "--input-type=module", "-e", guion],
                       input=json.dumps(cases), capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[:400]
    ts = json.loads(r.stdout)
    py = [M.compare_series([tuple(x) for x in a], [tuple(x) for x in b], [tuple(x) for x in h])
          for h, a, b in cases]
    py = json.loads(json.dumps(py))
    verdicts = [p["verdict"] for p in py]
    assert "outside_noise" in verdicts and "within_noise" in verdicts and "cannot_tell" in verdicts
    for i, (p, t) in enumerate(zip(py, ts)):
        assert p == t, f"case {i}: {p} != {t}"


@pytest.mark.skipif(not METHOD.exists(), reason="needs ts/dist/method.js")
def test_the_main_sleep_rule_picks_the_same_night_in_both():
    from oura_mcp import method as M
    records = [
        {"day": "2026-01-01", "type": "long_sleep", "total_sleep_duration": 25000, "average_hrv": 40},
        {"day": "2026-01-01", "type": "late_nap", "total_sleep_duration": 1800, "average_hrv": 90},
        {"day": "2026-01-02", "type": "long_sleep", "total_sleep_duration": 20000, "average_hrv": 50},
        {"day": "2026-01-02", "type": "long_sleep", "total_sleep_duration": 26000, "average_hrv": 44},
        {"day": "2026-01-03", "type": "sleep", "total_sleep_duration": 3000, "average_hrv": 70},
        {"day": "2026-01-04", "type": "long_sleep", "total_sleep_duration": 26000, "average_hrv": None},
        {"day": "2026-01-05", "type": "long_sleep", "total_sleep_duration": 26000, "average_hrv": True},
    ]
    guion = (
        f'import {{ series }} from "{METHOD}";\n'
        'const d = JSON.parse(await new Promise(r => {'
        "  let s = ''; process.stdin.on('data', c => s += c);"
        "  process.stdin.on('end', () => r(s)); }));\n"
        "console.log(JSON.stringify(series(d, 'sleep', 'average_hrv')));"
    )
    r = subprocess.run(["node", "--input-type=module", "-e", guion],
                       input=json.dumps(records), capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[:400]
    assert json.loads(r.stdout) == json.loads(json.dumps(M.series(records, "sleep", "average_hrv")))
