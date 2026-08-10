"""The command line, which nothing exercised.

IT NEVER TOUCHES THE NETWORK: every branch that would is replaced.

The branch that matters is `--forget`. Someone runs it because they want their
Oura credentials gone, and a dispatch bug that skipped it would print
`{"forgotten": true}` over an untouched refresh token — the package's own thesis
turned on the one command whose entire job is to be believed.
"""

import json

import pytest

from oura_mcp import __main__ as m


def _run(capsys, *args) -> tuple[int, str, str]:
    code = m.cli(list(args))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_an_unknown_flag_is_refused_and_says_so_on_stderr(capsys):
    """ON STDERR, NOT STDOUT. When this process is an MCP server, anything on
    stdout that isn't JSON-RPC breaks the channel — so a typo would take the
    whole session down instead of printing a complaint."""
    code, out, err = _run(capsys, "--revisar")
    assert code == 2
    assert out == "", "nothing may reach stdout"
    assert "--revisar" in err


def test_help_goes_to_stdout_because_it_was_asked_for(capsys):
    code, out, err = _run(capsys, "--help")
    assert code == 0 and "oura-mcp" in out


def test_manual_alone_is_refused_instead_of_starting_the_server(capsys):
    """`--manual` on its own means nothing, and starting the server because of
    it would be the old silence all over again."""
    code, out, err = _run(capsys, "--manual")
    assert code == 2 and "--authorize" in err


def test_forget_actually_calls_forget(capsys, monkeypatch):
    """The command whose only job is to be believed."""
    llamado = []
    monkeypatch.setattr("oura_mcp.credentials.forget", lambda: llamado.append(True))
    code, out, err = _run(capsys, "--forget")

    assert code == 0
    assert llamado == [True], "it reported success without erasing anything"
    assert json.loads(out)["forgotten"] is True


def test_a_failed_authorization_exits_nonzero(capsys, monkeypatch):
    """A shell script chaining `oura-mcp --authorize && …` has to be able to
    tell. Printing the error and exiting 0 is the same lie in a different
    place."""
    from oura_mcp.client import OuraError
    monkeypatch.setattr("oura_mcp.authorize.authorize",
                        lambda manual=False: (_ for _ in ()).throw(OuraError("nope")))
    code, out, err = _run(capsys, "--authorize")
    assert code == 1
    assert json.loads(out)["authorized"] is False


def test_authorize_passes_manual_through(capsys, monkeypatch):
    visto = {}
    monkeypatch.setattr("oura_mcp.authorize.authorize",
                        lambda manual=False: visto.setdefault("manual", manual) or {"ok": True})
    _run(capsys, "--authorize", "--manual")
    assert visto["manual"] is True


# ── `oura_check`: the thing you run when you are already stuck ──────────────
def test_the_self_check_never_reveals_the_token(monkeypatch):
    """Diagnostic output is the single most-copied text there is — into chats,
    into issues, into screenshots. It reports the token's LENGTH, never the
    token."""
    from oura_mcp import server as S
    monkeypatch.setenv("OURA_PAT", "SUPERSECRETO-NO-DEBE-SALIR-12345")
    monkeypatch.delenv("OURA_SANDBOX", raising=False)
    monkeypatch.setattr("oura_mcp.client._request",
                        lambda *a, **k: {"data": [{"day": "2026-01-01", "score": 7}]})

    salida = json.dumps(S.check(), ensure_ascii=False)
    assert "SUPERSECRETO" not in salida
    assert "12345" not in salida


def test_the_self_check_never_reveals_a_health_value(monkeypatch):
    """It reports WHICH fields came back, never what was in them. Someone
    debugging shouldn't have to publish their sleep score to prove the
    connection works."""
    from oura_mcp import server as S
    monkeypatch.setenv("OURA_PAT", "x" * 32)
    monkeypatch.delenv("OURA_SANDBOX", raising=False)
    monkeypatch.setattr(
        "oura_mcp.client._request",
        lambda *a, **k: {"data": [{"day": "2026-01-01", "score": 73,
                                   "total_sleep_duration": 27000}]})

    out = S.check()
    salida = json.dumps(out, ensure_ascii=False)
    assert "score" in salida, "the field NAMES are the point of the check"
    assert "73" not in salida, "a health value escaped"
    assert "27000" not in salida


def test_the_sandbox_self_check_says_the_data_is_not_yours(monkeypatch):
    """It is the first thing someone runs after installing, in the mode that
    ships turned on."""
    from oura_mcp import server as S
    monkeypatch.setenv("OURA_SANDBOX", "1")
    monkeypatch.setattr("oura_mcp.client._request",
                        lambda *a, **k: {"data": [{"day": "2026-01-01"}]})
    out = S.check()
    assert out["mode"] == "sandbox"
    assert "not yours" in out["data"]
