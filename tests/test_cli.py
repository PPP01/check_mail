from mail_check_app.cli import build_cron_line, build_parser
from mail_check_app.runtime import PROJECT_ROOT


def test_build_cron_line_uses_project_log_path_by_default() -> None:
    line = build_cron_line(
        python_executable="/opt/venv/bin/python",
        script_path="/opt/check_emails/mail_check.py",
    )

    assert ">> " + str(PROJECT_ROOT / "log" / "mail_check.log") + " 2>&1" in line


def test_build_cron_line_uses_custom_log_path() -> None:
    line = build_cron_line(
        log_file="/var/log/check_mail/mail_check.log",
        python_executable="/opt/venv/bin/python",
        script_path="/opt/check_emails/mail_check.py",
    )

    assert ">> /var/log/check_mail/mail_check.log 2>&1" in line


def test_check_parser_reads_soft_delete_match_from_env(monkeypatch) -> None:
    monkeypatch.setenv("IMAP_HOST", "imap.example.net")
    monkeypatch.setenv("IMAP_USER", "user@example.net")
    monkeypatch.setenv("IMAP_PASSWORD", "secret")
    monkeypatch.setenv("MAIL_SOFT_DELETE_MATCH", "1")

    parser = build_parser()
    args = parser.parse_args(["check"])

    assert args.soft_delete_match is True
