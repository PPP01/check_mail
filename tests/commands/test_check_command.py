from datetime import datetime, timezone
from email.message import EmailMessage
from types import SimpleNamespace

from mail_check_app.commands.check_command import collect_valid_matches, run_check_command, run_email_check
from mail_check_app.shared.jwt_utils import create_mailcheck_jwt


def _args() -> SimpleNamespace:
    return SimpleNamespace(
        mail_jwt_secret="x" * 32,
        no_icinga_submit=False,
        icinga_passive_check=True,
    )


def test_run_email_check_requires_jwt_secret() -> None:
    args = _args()
    args.mail_jwt_secret = ""

    rc, output = run_email_check(args)

    assert rc == 3
    assert "MAIL_CHECK_JWT_SECRET" in output


def test_run_email_check_rejects_short_jwt_secret() -> None:
    args = _args()
    args.mail_jwt_secret = "short"

    rc, output = run_email_check(args)

    assert rc == 3
    assert "at least 32 characters" in output


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


def test_collect_valid_matches_expunge_depends_on_soft_delete_flag(monkeypatch) -> None:
    secret = "x" * 32
    token = create_mailcheck_jwt(secret, datetime.now(timezone.utc))
    message = EmailMessage()
    message["X-Mail-Check-Jwt"] = token
    message.set_content("body")
    raw_message = message.as_bytes()

    class FakeImap:
        def __init__(self) -> None:
            self.stored = []
            self.expunge_calls = 0

        def login(self, *_args):
            return "OK", []

        def select(self, _mailbox):
            return "OK", []

        def fetch(self, _msg_id, _what):
            return "OK", [(b"1 (RFC822)", raw_message)]

        def store(self, msg_id, action, flag):
            self.stored.append((msg_id, action, flag))
            return "OK", []

        def expunge(self):
            self.expunge_calls += 1
            return "OK", []

        def close(self):
            return "OK", []

        def logout(self):
            return "BYE", []

    def _run_with_soft_delete(soft_delete: bool):
        fake_imap = FakeImap()
        args = SimpleNamespace(
            imap_host="imap.example.net",
            imap_port=993,
            imap_user="user",
            imap_password="pw",
            mailbox="INBOX",
            mail_jwt_secret=secret,
            mail_jwt_max_age_seconds=60,
            delete_match=True,
            soft_delete_match=soft_delete,
        )
        valid_ids, _metrics = collect_valid_matches(args, fake_imap, [b"1"])
        return fake_imap, valid_ids

    hard_delete_imap, hard_valid_ids = _run_with_soft_delete(False)
    assert hard_valid_ids == [b"1"]
    assert hard_delete_imap.stored == [(b"1", "+FLAGS", "\\Deleted")]
    assert hard_delete_imap.expunge_calls == 1

    soft_delete_imap, soft_valid_ids = _run_with_soft_delete(True)
    assert soft_valid_ids == [b"1"]
    assert soft_delete_imap.stored == [(b"1", "+FLAGS", "\\Deleted")]
    assert soft_delete_imap.expunge_calls == 0


def test_run_email_check_uses_single_connection(monkeypatch) -> None:
    secret = "x" * 32
    token = create_mailcheck_jwt(secret, datetime.now(timezone.utc))
    message = EmailMessage()
    message["X-Mail-Check-Jwt"] = token
    message.set_content("body")
    raw_message = message.as_bytes()

    class FakeImap:
        def __init__(self) -> None:
            self.login_calls = 0
            self.search_calls = 0
            self.select_calls = 0
            self.fetch_calls = 0
            self.close_calls = 0
            self.logout_calls = 0

        def login(self, *_args):
            self.login_calls += 1
            return "OK", []

        def select(self, _mailbox):
            self.select_calls += 1
            return "OK", []

        def search(self, _charset, *_criteria):
            self.search_calls += 1
            return "OK", [b"1"]

        def fetch(self, _msg_id, _what):
            self.fetch_calls += 1
            return "OK", [(b"1 (RFC822)", raw_message)]

        def close(self):
            self.close_calls += 1
            return "OK", []

        def logout(self):
            self.logout_calls += 1
            return "BYE", []

    fake_imap = FakeImap()
    monkeypatch.setattr(
        "mail_check_app.commands.check_command.imaplib.IMAP4_SSL",
        lambda *_args, **_kwargs: fake_imap,
    )

    args = SimpleNamespace(
        imap_host="imap.example.net",
        imap_port=993,
        imap_user="user",
        imap_password="pw",
        mailbox="INBOX",
        mail_jwt_secret=secret,
        mail_jwt_max_age_seconds=60,
        include_seen=False,
        subject_contains="",
        from_contains="",
        body_contains="",
        delete_match=False,
    )

    rc, output = run_email_check(args)

    assert rc == 0
    assert "Mail Check OK" in output
    assert fake_imap.login_calls == 1
    assert fake_imap.select_calls == 2  # Once in search, once in collect_valid_matches (still in the same connection)
    assert fake_imap.search_calls == 1
    assert fake_imap.fetch_calls == 1
    assert fake_imap.close_calls == 1
    assert fake_imap.logout_calls == 1
