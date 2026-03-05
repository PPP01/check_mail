import os
import shlex
import smtplib
import ssl
import subprocess
import time
from datetime import datetime, timezone
from email.message import EmailMessage

from ..shared.jwt_utils import create_mailcheck_jwt


def build_send_message(args) -> EmailMessage:
    """Create the outbound test message including MailCheck JWT metadata."""
    sent_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    jwt_value = create_mailcheck_jwt(args.mail_jwt_secret, datetime.now(timezone.utc))
    body = f"MailCheckJwt: {jwt_value}\nMailCheckSentAt: {sent_at}\n\n{args.send_body}"

    message = EmailMessage()
    message["From"] = args.send_from
    message["To"] = args.send_to
    message["Subject"] = args.send_subject
    message["X-Mail-Check-Jwt"] = jwt_value
    message["X-Mail-Check-Sent-At"] = sent_at
    message.set_content(body)
    return message


def send_via_sendmail(args, message: EmailMessage) -> None:
    """Send the message using a local sendmail-compatible command."""
    command = shlex.split(args.sendmail_command)
    if not command:
        raise RuntimeError("MAIL_SEND_SENDMAIL_COMMAND is empty.")

    has_sender_flag = False
    for idx, token in enumerate(command):
        if token == "-f":
            has_sender_flag = True
            break
        if token.startswith("-f") and len(token) > 2:
            has_sender_flag = True
            break
        if token == "-r":
            has_sender_flag = True
            break
        if token.startswith("-r") and len(token) > 2:
            has_sender_flag = True
            break
        if token == "--":
            break
        if token in {"-f", "-r"} and idx + 1 < len(command):
            has_sender_flag = True
            break
    if args.send_from and not has_sender_flag:
        command.extend(["-f", args.send_from])

    proc = subprocess.run(
        command,
        input=message.as_string(),
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        stderr = proc.stderr.strip() or proc.stdout.strip()
        raise RuntimeError(f"sendmail command failed (exit={proc.returncode}): {stderr}")


def send_via_mail_cmd(args) -> None:
    sent_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    jwt_value = create_mailcheck_jwt(args.mail_jwt_secret, datetime.now(timezone.utc))
    body = f"MailCheckJwt: {jwt_value}\nMailCheckSentAt: {sent_at}\n\n{args.send_body}"

    command = shlex.split(args.mail_command)
    if not command:
        raise RuntimeError("MAIL_SEND_MAIL_COMMAND is empty.")
    command.extend(["-s", args.send_subject])
    if args.send_from:
        command.extend(["-r", args.send_from])
    command.append(args.send_to)

    proc = subprocess.run(
        command,
        input=body,
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        stderr = proc.stderr.strip() or proc.stdout.strip()
        raise RuntimeError(f"mail command failed (exit={proc.returncode}): {stderr}")


def send_via_smtp(args, message: EmailMessage) -> None:
    """Send the message directly via SMTP/SMTPS with optional auth."""
    if not args.smtp_host:
        raise RuntimeError("MAIL_SEND_SMTP_HOST/--smtp-host is required for smtp backend.")

    smtp_cls = smtplib.SMTP_SSL if args.smtp_ssl else smtplib.SMTP
    context = ssl.create_default_context()
    with smtp_cls(args.smtp_host, args.smtp_port, timeout=15) as client:
        if not args.smtp_ssl and args.smtp_starttls:
            client.starttls(context=context)
        if args.smtp_user:
            client.login(args.smtp_user, args.smtp_password)
        client.send_message(message)


def run_send_command(args) -> int:
    """Execute the `send` command and print Nagios-compatible output."""
    if not args.mail_jwt_secret:
        print("ERROR - MAIL_CHECK_JWT_SECRET is required for send command.")
        return 3

    if not args.send_to:
        imap_user = os.getenv("IMAP_USER", "").strip()
        if "@" in imap_user:
            args.send_to = imap_user
    if not args.send_from:
        match_from = os.getenv("MAIL_FROM_CONTAINS", "").strip()
        if "@" in match_from:
            args.send_from = match_from
        elif args.send_to:
            args.send_from = args.send_to

    if not args.send_to or not args.send_from:
        print(
            "ERROR - send requires sender/recipient. Set MAIL_SEND_TO and MAIL_SEND_FROM "
            "or pass --send-to/--send-from."
        )
        return 3

    message = build_send_message(args)
    started = time.perf_counter()
    try:
        if args.send_backend == "sendmail":
            send_via_sendmail(args, message)
        elif args.send_backend == "mail":
            send_via_mail_cmd(args)
        elif args.send_backend == "smtp":
            send_via_smtp(args, message)
        else:
            print(f"ERROR - unsupported send backend: {args.send_backend}")
            return 3
    except Exception as exc:
        print(f"ERROR - send failed: {exc}")
        return 3

    send_seconds = max(0.0, time.perf_counter() - started)
    message_size = len(message.as_bytes())
    print(
        f"OK - send command delivered test mail via backend={args.send_backend}; "
        f"to={args.send_to}; subject={args.send_subject!r} "
        f"| send_command_seconds={send_seconds:.3f}s;;;; send_message_bytes={message_size}B;;;;"
    )
    return 0
