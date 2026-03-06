from types import SimpleNamespace

from mail_check_app.commands.send_command import run_send_command


def _args() -> SimpleNamespace:
    return SimpleNamespace(
        mail_jwt_secret="x" * 32,
        mail_jwt_max_age_seconds=86400,
        send_to="to@example.net",
        send_from="from@example.net",
        send_backend="sendmail",
        send_subject="subject",
        send_body="body",
        sendmail_command="/usr/sbin/sendmail -t -i",
        mail_command="/usr/bin/mail",
        smtp_host="",
        smtp_port=587,
        smtp_user="",
        smtp_password="",
        smtp_starttls=True,
        smtp_ssl=False,
    )


def test_run_send_command_requires_jwt_secret(capsys) -> None:
    args = _args()
    args.mail_jwt_secret = ""

    rc = run_send_command(args)

    captured = capsys.readouterr().out
    assert rc == 3
    assert "MAIL_CHECK_JWT_SECRET" in captured


def test_run_send_command_rejects_short_jwt_secret(capsys) -> None:
    args = _args()
    args.mail_jwt_secret = "short"

    rc = run_send_command(args)

    captured = capsys.readouterr().out
    assert rc == 3
    assert "mindestens 32 Zeichen" in captured


def test_run_send_command_sendmail_success(monkeypatch, capsys) -> None:
    args = _args()

    called = {"value": False}

    def _fake_send(_args, _message) -> None:
        called["value"] = True

    monkeypatch.setattr("mail_check_app.commands.send_command.send_via_sendmail", _fake_send)

    rc = run_send_command(args)

    captured = capsys.readouterr().out
    assert rc == 0
    assert called["value"] is True
    assert "OK - send command delivered test mail via backend=sendmail" in captured


def test_run_send_command_returns_error_when_backend_send_fails(monkeypatch, capsys) -> None:
    args = _args()

    def _fail(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("mail_check_app.commands.send_command.send_via_sendmail", _fail)

    rc = run_send_command(args)

    captured = capsys.readouterr().out
    assert rc == 3
    assert "ERROR - send failed" in captured
