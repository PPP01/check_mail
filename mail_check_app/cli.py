import argparse
import os
import sys
from pathlib import Path

from .runtime import env_bool


def build_cron_line(
    schedule: str = "*/5 * * * *",
    log_file: str = "/tmp/mail_check.log",
    python_executable: str = "",
    script_path: str = "",
) -> str:
    python_path = Path(python_executable) if python_executable else Path(sys.executable)
    script = Path(script_path) if script_path else Path(__file__).resolve()
    return f"{schedule} {python_path} {script} check >> {log_file} 2>&1"


def _add_mail_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--imap-host", default=os.getenv("IMAP_HOST"), required=not os.getenv("IMAP_HOST"))
    parser.add_argument("--imap-port", type=int, default=int(os.getenv("IMAP_PORT", "993")))
    parser.add_argument("--imap-user", default=os.getenv("IMAP_USER"), required=not os.getenv("IMAP_USER"))
    parser.add_argument("--imap-password", default=os.getenv("IMAP_PASSWORD"), required=not os.getenv("IMAP_PASSWORD"))
    parser.add_argument("--mailbox", default=os.getenv("IMAP_MAILBOX", "INBOX"))

    parser.add_argument("--subject-contains", default=os.getenv("MAIL_SUBJECT_CONTAINS", ""))
    parser.add_argument("--from-contains", default=os.getenv("MAIL_FROM_CONTAINS", ""))
    parser.add_argument("--body-contains", default=os.getenv("MAIL_BODY_CONTAINS", ""))
    parser.add_argument("--mail-jwt-secret", default=os.getenv("MAIL_CHECK_JWT_SECRET", ""))
    parser.add_argument(
        "--mail-jwt-max-age-seconds",
        type=int,
        default=int(os.getenv("MAIL_CHECK_JWT_MAX_AGE_SECONDS", "86400")),
    )
    parser.add_argument("--include-seen", action="store_true", default=os.getenv("MAIL_INCLUDE_SEEN", "0") == "1")
    parser.add_argument("--delete-match", action="store_true", default=os.getenv("MAIL_DELETE_MATCH", "0") == "1")


def _add_icinga_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--icinga-url", default=os.getenv("ICINGA_URL"))
    parser.add_argument("--icinga-user", default=os.getenv("ICINGA_USER"))
    parser.add_argument("--icinga-password", default=os.getenv("ICINGA_PASSWORD"))
    parser.add_argument("--icinga-host", default=os.getenv("ICINGA_HOST"))
    parser.add_argument("--icinga-service", default=os.getenv("ICINGA_SERVICE"))
    parser.add_argument("--icinga-verify-tls", action="store_true", default=os.getenv("ICINGA_VERIFY_TLS", "1") == "1")
    parser.add_argument("--debug-icinga", action="store_true", default=env_bool("ICINGA_DEBUG", "MAIL_DEBUG_ICINGA"))
    parser.add_argument(
        "--icinga-dry-run",
        action="store_true",
        default=env_bool("ICINGA_DRY_RUN", "MAIL_ICINGA_DRY_RUN"),
    )
    parser.add_argument(
        "--icinga-passive-check",
        action="store_true",
        default=os.getenv("ICINGA_PASSIVE_CHECK", "1") == "1",
        help="Enable passive Icinga submit for check command (env: ICINGA_PASSIVE_CHECK=0/1).",
    )


def _add_send_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--send-backend",
        default=os.getenv("MAIL_SEND_BACKEND", "sendmail"),
        choices=["sendmail", "mail", "smtp"],
        help="Mail send backend.",
    )
    parser.add_argument("--send-to", default=os.getenv("MAIL_SEND_TO", ""))
    parser.add_argument("--send-from", default=os.getenv("MAIL_SEND_FROM", ""))
    parser.add_argument("--mail-jwt-secret", default=os.getenv("MAIL_CHECK_JWT_SECRET", ""))
    parser.add_argument(
        "--mail-jwt-max-age-seconds",
        type=int,
        default=int(os.getenv("MAIL_CHECK_JWT_MAX_AGE_SECONDS", "86400")),
    )
    parser.add_argument(
        "--send-subject",
        default=os.getenv("MAIL_SEND_SUBJECT", "IcingaMail: Send test"),
    )
    parser.add_argument(
        "--send-body",
        default=os.getenv("MAIL_SEND_BODY", "IcingaMail Send test"),
    )

    parser.add_argument(
        "--sendmail-command",
        default=os.getenv("MAIL_SEND_SENDMAIL_COMMAND", "/usr/sbin/sendmail -t -i"),
        help="Command used for sendmail backend.",
    )
    parser.add_argument(
        "--mail-command",
        default=os.getenv("MAIL_SEND_MAIL_COMMAND", "/usr/bin/mail"),
        help="Command used for mail backend.",
    )

    parser.add_argument("--smtp-host", default=os.getenv("MAIL_SEND_SMTP_HOST", ""))
    parser.add_argument("--smtp-port", type=int, default=int(os.getenv("MAIL_SEND_SMTP_PORT", "587")))
    parser.add_argument("--smtp-user", default=os.getenv("MAIL_SEND_SMTP_USER", ""))
    parser.add_argument("--smtp-password", default=os.getenv("MAIL_SEND_SMTP_PASSWORD", ""))
    parser.add_argument(
        "--smtp-starttls",
        action="store_true",
        default=os.getenv("MAIL_SEND_SMTP_STARTTLS", "1") == "1",
    )
    parser.add_argument(
        "--smtp-ssl",
        action="store_true",
        default=os.getenv("MAIL_SEND_SMTP_SSL", "0") == "1",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Mail heartbeat check with optional Icinga2 passive submit via subcommands. "
            "Run without command to show help."
        )
    )

    parser.add_argument(
        "--print-cron-line",
        action="store_true",
        help="Print a cron line with the current python and script path, then exit.",
    )
    parser.add_argument("--config", "-c", default="", help="Optional full settings .env file to load.")

    subparsers = parser.add_subparsers(dest="command")

    check_parser = subparsers.add_parser(
        "check",
        help="Run mail heartbeat receive check and optionally submit passive result to Icinga.",
    )
    _add_mail_args(check_parser)
    _add_icinga_args(check_parser)
    check_parser.add_argument(
        "--no-icinga-submit",
        action="store_true",
        help="Skip passive Icinga API submit and return only plugin output + exit code.",
    )

    email_parser = subparsers.add_parser("email", help="Check mailbox only, no Icinga submit.")
    _add_mail_args(email_parser)

    icinga_parser = subparsers.add_parser("icinga", help="Submit test result to Icinga only.")
    _add_icinga_args(icinga_parser)
    icinga_parser.add_argument(
        "--test-exit-status",
        type=int,
        default=3,
        help="Exit status to submit for icinga test command.",
    )
    icinga_parser.add_argument(
        "--test-output",
        default="UNKNOWN - Icinga test only (no mailbox check).",
        help="Plugin output text for icinga test command.",
    )

    send_parser = subparsers.add_parser("send", help="Send test mail via configured backend.")
    _add_send_args(send_parser)

    template_parser = subparsers.add_parser(
        "template-config",
        help="Create match-criteria config from a mail source template.",
    )
    template_parser.add_argument(
        "--template-file",
        "-f",
        required=True,
        help="Path to template file (full mail source recommended).",
    )
    template_parser.add_argument(
        "--output",
        "-o",
        default="",
        help="Optional match-criteria output .env path (default: ./config/match_criteria_<name>.env).",
    )
    template_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing output match-criteria file.",
    )
    template_parser.add_argument(
        "--new-config",
        default="",
        help="Optional full settings config name/path created from settings.env.example.",
    )
    template_parser.add_argument(
        "--set-default",
        "-d",
        action="store_true",
        help="Write MAIL_ACTIVE_CONFIG into config/settings.env.",
    )

    return parser
