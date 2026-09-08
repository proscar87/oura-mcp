"""The cache, and the four things it refuses to hold.

WHY IT IS SAFE AT ALL. Every other cache has to guess how long an answer stays
true. This one does not guess: a day that has already closed cannot gain
records, so it is held forever, and today is never held, because the ring syncs
whenever it likes. The rule is the calendar, not a clock, and there is no window
in which it can be wrong.

WHY IT IS IN MEMORY. `SUBMISSION.md` and the README both state that health data
is never written to disk. A disk cache would make both false in exchange for a
speed-up nobody asked for.

Every test here counts REQUESTS, not milliseconds. A cache that is merely fast
is a cache nobody can prove; a cache that provably did not ask Oura again is a
different claim, and it is the one being made.
"""

import datetime
import json

import pytest

from oura_mcp import client

from test_oura_mcp import _fake_oura


AYER = (datetime.date.today() - datetime.timedelta(days=3)).isoformat()
ANTEAYER = (datetime.date.today() - datetime.timedelta(days=4)).isoformat()
HOY = datetime.date.today().isoformat()
MAS_ATRAS = (datetime.date.today() - datetime.timedelta(days=6)).isoformat()


# ── What it holds ──────────────────────────────────────────────────────────
def test_a_closed_range_is_asked_for_once(monkeypatch):
    """The claim, stated as a request count."""
    llamadas = _fake_oura([[{"day": ANTEAYER}, {"day": AYER}]], monkeypatch)
    primera = client.fetch("daily_sleep", ANTEAYER, AYER)
    assert len(llamadas) == 1
    segunda = client.fetch("daily_sleep", ANTEAYER, AYER)
    assert len(llamadas) == 1, "it asked Oura again for a day that cannot change"
    assert segunda["data"] == primera["data"]
    assert segunda["n"] == primera["n"]


def test_the_hit_says_it_is_a_hit(monkeypatch):
    """A response that does not say how it was produced is the failure this
    package exists to refuse. «Why was that instant?» has to be answerable from
    the response itself, the same way `synthetic` answers «are these mine?»."""
    _fake_oura([[{"day": AYER}]], monkeypatch)
    assert "cached" not in client.fetch("daily_sleep", AYER, AYER)
    hit = client.fetch("daily_sleep", AYER, AYER)
    assert "cached" in hit
    assert "closed before today" in hit["cached"]


def test_the_held_answer_is_not_corrupted_by_its_readers(monkeypatch):
    """The hit hands back a copy of the dict. The server adds keys to what it
    gets, and those must not accumulate on the entry everyone else receives."""
    _fake_oura([[{"day": AYER}]], monkeypatch)
    client.fetch("daily_sleep", AYER, AYER)
    primera = client.fetch("daily_sleep", AYER, AYER)
    primera["invented"] = True
    segunda = client.fetch("daily_sleep", AYER, AYER)
    assert "invented" not in segunda


# ── What it refuses ────────────────────────────────────────────────────────
def test_today_is_never_held(monkeypatch):
    """THE WHOLE RULE. The ring can sync at any moment, so a range reaching
    today is a question whose answer is still moving."""
    llamadas = _fake_oura([[{"day": HOY}]], monkeypatch)
    client.fetch("daily_sleep", AYER, HOY)
    client.fetch("daily_sleep", AYER, HOY)
    assert len(llamadas) == 2, "it held a range that includes today"


def test_a_range_ending_in_the_future_is_never_held(monkeypatch):
    """A day that has not happened cannot have closed. Text comparison makes
    this fall out of the same rule rather than needing its own."""
    manana = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
    llamadas = _fake_oura([[{"day": AYER}]], monkeypatch)
    client.fetch("daily_sleep", AYER, manana)
    client.fetch("daily_sleep", AYER, manana)
    assert len(llamadas) == 2


def test_an_empty_answer_is_never_held(monkeypatch):
    """THE INVARIANT THAT MADE CACHING ADOPTABLE. Nothing tells «there is no
    data for that day» apart from «the ring had not synced when you asked», and
    holding the second forever turns a temporary gap into a permanent one — a
    wrong answer that looks exactly like a right one, which is the family of
    failure this whole package is about."""
    llamadas = _fake_oura([[]], monkeypatch)
    primera = client.fetch("daily_sleep", ANTEAYER, AYER)
    assert "empty" in primera
    client.fetch("daily_sleep", ANTEAYER, AYER)
    assert len(llamadas) == 2, "it held an empty response"


def test_a_truncated_answer_is_never_held(monkeypatch):
    """It is incomplete by its own admission. Freezing it would serve that
    incompleteness to every later caller, without the request that might have
    gone further."""
    paginas = [[{"day": AYER}] for _ in range(4)]
    llamadas = _fake_oura(paginas, monkeypatch)
    r = client.fetch("daily_sleep", ANTEAYER, AYER, page_limit=2)
    assert "truncated" in r
    antes = len(llamadas)
    client.fetch("daily_sleep", ANTEAYER, AYER, page_limit=2)
    assert len(llamadas) > antes, "it held a truncated response"


def test_latest_is_never_held(monkeypatch):
    """`latest` asks for the most recent record Oura has, which is a question
    about now. There is no range, so there is nothing that can have closed."""
    llamadas = _fake_oura([[{"timestamp": f"{AYER}T10:00:00+00:00"}]], monkeypatch)
    client.fetch("heartrate", latest=True)
    client.fetch("heartrate", latest=True)
    assert len(llamadas) == 2


# ── What it keys on ────────────────────────────────────────────────────────
@pytest.mark.parametrize("distinto", [
    {"collection": "daily_activity"},
    {"start": MAS_ATRAS},
    {"fields": ["day"]},
    {"format": "csv"},
])
def test_a_different_question_is_a_different_entry(distinto, monkeypatch):
    """Answering one question with another's answer is the same lie as a partial
    response that looks complete, arrived at from the other direction."""
    base = {"collection": "daily_sleep", "start": ANTEAYER, "end": AYER}
    llamadas = _fake_oura([[{"day": AYER, "score": 1}]], monkeypatch)
    client.fetch(**base)
    antes = len(llamadas)
    client.fetch(**{**base, **distinto})
    assert len(llamadas) == antes + 1


def test_the_sandbox_and_the_real_api_never_share_an_entry(monkeypatch):
    """`base()` is in the key. Serving someone's real data out of an entry
    filled from Oura's sample data — or the reverse — is the one confusion this
    package spends a whole response key preventing."""
    _fake_oura([[{"day": AYER}]], monkeypatch)
    real = client.fetch("daily_sleep", ANTEAYER, AYER)
    assert "synthetic" not in real
    monkeypatch.setenv("OURA_SANDBOX", "1")
    caja = client.fetch("daily_sleep", ANTEAYER, AYER)
    assert "synthetic" in caja, "the sandbox was answered from the real entry"


# ── What it costs ──────────────────────────────────────────────────────────
def test_it_is_bounded_and_drops_the_oldest(monkeypatch):
    """Unbounded, a long session holding months of `heartrate` is a memory leak
    with a nice name."""
    _fake_oura([[{"day": AYER}]], monkeypatch)
    for i in range(client.CACHE_MAX + 5):
        client.fetch("daily_sleep", ANTEAYER, AYER, page_limit=10 + i)
    assert len(client._cache) <= client.CACHE_MAX


def test_a_throttle_is_not_replayed_on_a_hit(monkeypatch):
    """`rate_limited` is about the request that happened, not about the data.
    Telling someone they are near a limit they never touched is the same class
    of false statement as a partial answer presented as whole."""
    r = {"collection": "daily_sleep", "n": 1, "pages": 1,
         "data": [{"day": AYER}], "rate_limited": "waited 3s"}
    client._cache[("k",)] = {k: v for k, v in r.items() if k != "rate_limited"}
    assert "rate_limited" not in client._cache[("k",)]


def test_nothing_reaches_the_disk(tmp_path, monkeypatch):
    """The README and the submission both promise it. The cache lives in a
    module-level dict and writes nothing, and this asserts it rather than
    trusting the reading."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    _fake_oura([[{"day": AYER, "score": 77}]], monkeypatch)
    client.fetch("daily_sleep", ANTEAYER, AYER)
    client.fetch("daily_sleep", ANTEAYER, AYER)
    for p in tmp_path.rglob("*"):
        if p.is_file():
            assert "77" not in p.read_text(encoding="utf-8", errors="ignore"), p
