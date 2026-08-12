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
        f'import {{ sizeWarning, toCsv, shiftDays, dayOf }} from "{DIST}";\n'
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
