from types import SimpleNamespace

from mail_check_app.commands.icinga_command import run_icinga_command


def _args() -> SimpleNamespace:
    return SimpleNamespace(
        test_exit_status=0,
        test_output="OK - test",
    )


def test_run_icinga_command_fails_when_required_args_missing(monkeypatch, capsys) -> None:
    args = _args()

    monkeypatch.setattr("mail_check_app.commands.icinga_command.missing_icinga_args", lambda _a: ["ICINGA_URL/--icinga-url"])

    rc = run_icinga_command(args)

    captured = capsys.readouterr().out
    assert rc == 3
    assert "Icinga settings missing" in captured


def test_run_icinga_command_submits_test_payload(monkeypatch, capsys) -> None:
    args = _args()

    monkeypatch.setattr("mail_check_app.commands.icinga_command.missing_icinga_args", lambda _a: [])
    monkeypatch.setattr("mail_check_app.commands.icinga_command.submit_passive_result", lambda *_: "submitted")

    rc = run_icinga_command(args)

    captured = capsys.readouterr().out
    assert rc == 0
    assert "Icinga submit OK - submitted" in captured
    assert "TEST - icinga command submitted test payload" in captured
