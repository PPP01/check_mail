from types import SimpleNamespace

from mail_check_app.commands.check_command import run_check_command, run_email_check


def _args() -> SimpleNamespace:
    return SimpleNamespace(
        mail_jwt_secret="secret",
        no_icinga_submit=False,
        icinga_passive_check=True,
    )


def test_run_email_check_requires_jwt_secret() -> None:
    args = _args()
    args.mail_jwt_secret = ""

    rc, output = run_email_check(args)

    assert rc == 3
    assert "MAIL_CHECK_JWT_SECRET" in output


def test_run_check_command_without_submit_returns_email_result(monkeypatch, capsys) -> None:
    args = _args()
    args.no_icinga_submit = True

    monkeypatch.setattr("mail_check_app.commands.check_command.run_email_check", lambda _a: (0, "OK - mail found"))

    rc = run_check_command(args)

    captured = capsys.readouterr().out
    assert rc == 0
    assert "OK - mail found" in captured


def test_run_check_command_fails_when_icinga_args_missing(monkeypatch, capsys) -> None:
    args = _args()

    monkeypatch.setattr("mail_check_app.commands.check_command.run_email_check", lambda _a: (2, "CRITICAL - no mail"))
    monkeypatch.setattr("mail_check_app.commands.check_command.missing_icinga_args", lambda _a: ["ICINGA_URL/--icinga-url"])

    rc = run_check_command(args)

    captured = capsys.readouterr().out
    assert rc == 3
    assert "Icinga settings missing" in captured


def test_run_check_command_submits_to_icinga_on_success(monkeypatch, capsys) -> None:
    args = _args()

    monkeypatch.setattr("mail_check_app.commands.check_command.run_email_check", lambda _a: (0, "OK - mail found"))
    monkeypatch.setattr("mail_check_app.commands.check_command.missing_icinga_args", lambda _a: [])
    monkeypatch.setattr("mail_check_app.commands.check_command.submit_passive_result", lambda *_: "submitted")

    rc = run_check_command(args)

    captured = capsys.readouterr().out
    assert rc == 0
    assert "Icinga submit OK - submitted" in captured
    assert "OK - mail found" in captured
