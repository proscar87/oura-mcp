"""Sample data must never reach a model unlabeled.

This is the package's own thesis turned on itself. The server exists because
Oura answers with something that LOOKS right when it can't give you what you
asked for. `oura_check` said the sandbox data was synthetic and the queries did
not — so a fresh install, in the default configuration, answered "how did I
sleep?" with a score out of Oura's fake data and nothing marking it.

The checkbox defaults to on, and that's deliberate: turning it off gives a
stranger with no Oura application an error on their first question instead of a
working demonstration. On is only defensible because of these tests.

THEY NEVER TOUCH THE NETWORK: the sandbox client is not called, only the
response assembly.
"""

import pytest

from oura_mcp import client
from oura_mcp.collections import COLLECTIONS


@pytest.fixture
def sandbox(monkeypatch):
    monkeypatch.setenv("OURA_SANDBOX", "1")
    monkeypatch.delenv("OURA_PAT", raising=False)
    monkeypatch.delenv("OURA_PAT_FILE", raising=False)


def _fake(monkeypatch, records):
    """Stub the one function that reaches the network, like the other tests do.

    Pagination lives inline in `fetch`, so there's no page-level seam to stub —
    and going lower is better anyway: this exercises the real trimming, the real
    CSV, and the real empty-reason path."""
    monkeypatch.setattr(client, "_request",
                        lambda *a, **k: {"data": records, "next_token": None})


def test_every_sandbox_query_is_marked(sandbox, monkeypatch):
    """Every collection, not the one that got tested by hand."""
    _fake(monkeypatch, [{"day": "2026-01-15", "score": 73}])
    for name in COLLECTIONS:
        if name in client.WITHOUT_SANDBOX:
            continue
        out = client.fetch(name, "2026-01-15", "2026-01-15")
        assert "synthetic" in out, name


def test_it_is_marked_even_when_empty(sandbox, monkeypatch):
    """An empty answer is the one most likely to be read as «you have no data»."""
    _fake(monkeypatch, [])
    out = client.fetch("daily_sleep", "2026-01-15", "2026-01-15")
    assert "synthetic" in out and "empty" in out


def test_it_is_marked_in_csv_too(sandbox, monkeypatch):
    """CSV is a wall of numbers with no place to put a caveat."""
    _fake(monkeypatch, [{"day": "2026-01-15", "score": 73}])
    out = client.fetch("daily_sleep", "2026-01-15", "2026-01-15", format="csv")
    assert "synthetic" in out


def test_the_marker_says_it_is_not_theirs_and_names_the_next_step(sandbox, monkeypatch):
    """Wording, not just presence. «Sandbox mode» alone means nothing to a
    person, and a warning without a next step leaves them stuck."""
    _fake(monkeypatch, [{"day": "2026-01-15"}])
    m = client.fetch("daily_sleep", "2026-01-15", "2026-01-15")["synthetic"].lower()
    assert "not this person's" in m
    assert "connect" in m


def test_real_mode_does_not_carry_the_marker(monkeypatch):
    """Otherwise it becomes noise on every answer and stops being read."""
    monkeypatch.delenv("OURA_SANDBOX", raising=False)
    monkeypatch.setenv("OURA_PAT", "x" * 32)
    _fake(monkeypatch, [{"day": "2026-01-15"}])
    assert "synthetic" not in client.fetch("daily_sleep", "2026-01-15", "2026-01-15")
