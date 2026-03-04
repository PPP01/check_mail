#!/usr/bin/env python3
import argparse
import base64
import hashlib
import hmac
import re
import shlex
import imaplib
import json
import os
import secrets
import ssl
import smtplib
import subprocess
import sys
import time
import urllib.error
import urllib.request
import unicodedata
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
from email.message import EmailMessage
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_ENV_PATH = PROJECT_ROOT / "config" / "settings.env"
DEFAULT_ENV_EXAMPLE_PATH = PROJECT_ROOT / "config" / "settings.env.example"


def _resolve_env_path(value: str) -> Path:
    raw_path = Path(value)
    if raw_path.is_absolute():
        return raw_path
    return (PROJECT_ROOT / raw_path).resolve()


def _env_bool(primary_key: str, fallback_key: str, default: str = "0") -> bool:
    value = os.getenv(primary_key)
    if value is None:
        value = os.getenv(fallback_key, default)
    return value == "1"


def _read_env_key(path: Path, key: str) -> str:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                name, value = line.split("=", 1)
                if name.strip() != key:
                    continue
                cleaned = value.strip()
                if (cleaned.startswith("'") and cleaned.endswith("'")) or (
                    cleaned.startswith('"') and cleaned.endswith('"')
                ):
                    cleaned = cleaned[1:-1]
                return cleaned.strip()
    except OSError as exc:
        raise RuntimeError(f"Could not read env file {path}: {exc}") from exc
    return ""


def load_runtime_env(config_override: str = "", require_active_profile: bool = True) -> str:
    load_dotenv(dotenv_path=DEFAULT_ENV_PATH, override=False)

    selected_config = config_override.strip() if config_override else ""
    if selected_config:
        selected_path = _resolve_env_path(selected_config)
        if not selected_path.exists():
            raise RuntimeError(
                f"Configured env file not found: {selected_config} (resolved: {selected_path})"
            )
        selected_active_profile = _read_env_key(selected_path, "MAIL_ACTIVE_CONFIG")
        if not selected_active_profile and require_active_profile:
            raise RuntimeError(
                f"Configured env file must define non-empty MAIL_ACTIVE_CONFIG: {selected_path}"
            )
        load_dotenv(dotenv_path=selected_path, override=True)

    active_profile = os.getenv("MAIL_ACTIVE_CONFIG", "").strip()
    if not active_profile:
        return ""

    profile_path = _resolve_env_path(active_profile)
    if not profile_path.exists():
        message = (
            f"Configured active profile not found: {active_profile} (resolved: {profile_path})"
        )
        if require_active_profile:
            raise RuntimeError(message)
        return message
    load_dotenv(dotenv_path=profile_path, override=True)
    return ""


def build_cron_line(schedule: str = "*/5 * * * *", log_file: str = "/tmp/mail_check.log") -> str:
    python_path = Path(sys.executable)
    script_path = Path(__file__).resolve()
    return f"{schedule} {python_path} {script_path} check >> {log_file} 2>&1"


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
    parser.add_argument("--debug-icinga", action="store_true", default=_env_bool("ICINGA_DEBUG", "MAIL_DEBUG_ICINGA"))
    parser.add_argument(
        "--icinga-dry-run",
        action="store_true",
        default=_env_bool("ICINGA_DRY_RUN", "MAIL_ICINGA_DRY_RUN"),
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


def _decode_header_val(value: str) -> str:
    # Keep criteria ASCII-safe and quote as IMAP string atom.
    safe = value.encode("ascii", errors="ignore").decode("ascii")
    escaped = safe.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * ((4 - len(value) % 4) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _create_mailcheck_jwt(secret: str, issued_at: datetime) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    iat = int(issued_at.timestamp())
    payload = {
        "iss": "mail-check",
        "sub": "mail-delivery-check",
        "iat": iat,
        "jti": secrets.token_hex(12),
    }
    header_b64 = _b64url_encode(json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    signature = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    signature_b64 = _b64url_encode(signature)
    return f"{header_b64}.{payload_b64}.{signature_b64}"


def _verify_mailcheck_jwt(token: str, secret: str, max_age_seconds: int) -> datetime:
    parts = token.split(".")
    if len(parts) != 3:
        raise RuntimeError("JWT format invalid.")

    header_b64, payload_b64, signature_b64 = parts
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    expected_signature = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    try:
        provided_signature = _b64url_decode(signature_b64)
    except Exception as exc:
        raise RuntimeError("JWT signature encoding invalid.") from exc
    if not hmac.compare_digest(expected_signature, provided_signature):
        raise RuntimeError("JWT signature invalid.")

    try:
        header = json.loads(_b64url_decode(header_b64).decode("utf-8"))
        payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError("JWT payload invalid.") from exc

    if header.get("alg") != "HS256":
        raise RuntimeError("JWT algorithm not supported.")

    iat = payload.get("iat")
    if not isinstance(iat, int):
        raise RuntimeError("JWT iat claim missing.")

    issued_at = datetime.fromtimestamp(iat, tz=timezone.utc)
    now_utc = datetime.now(timezone.utc)
    max_age = max(1, max_age_seconds)
    age = (now_utc - issued_at).total_seconds()
    if age < 0:
        raise RuntimeError("JWT iat is in the future.")
    if age > max_age:
        raise RuntimeError("JWT expired.")

    return issued_at


def _parse_template_sections(path: str) -> Tuple[Dict[str, str], List[str]]:
    headers: Dict[str, str] = {}
    body_lines: List[str] = []
    current_name = ""
    current_value_parts: List[str] = []
    in_header_block = True
    saw_header = False

    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for raw_line in f:
            line = raw_line.rstrip("\r\n")
            if in_header_block and not line:
                if current_name:
                    headers[current_name] = " ".join(current_value_parts).strip()
                    current_name = ""
                    current_value_parts = []
                if saw_header:
                    in_header_block = False
                continue

            if not in_header_block:
                body_lines.append(line)
                continue

            if line[0] in (" ", "\t") and current_name:
                current_value_parts.append(line.strip())
                continue

            if ":" not in line:
                continue

            if current_name:
                headers[current_name] = " ".join(current_value_parts).strip()

            name, value = line.split(":", 1)
            current_name = name.strip()
            current_value_parts = [value.strip()]
            saw_header = True

    if current_name:
        headers[current_name] = " ".join(current_value_parts).strip()

    # For full mail source templates, decode body content via email parser
    # to avoid quoted-printable hard wraps polluting body criteria.
    try:
        with open(path, "rb") as f:
            message = BytesParser(policy=policy.default).parse(f)
        parsed_body = _extract_body_text(message).splitlines()
        if any(line.strip() for line in parsed_body):
            body_lines = parsed_body
    except Exception:
        pass

    return headers, body_lines


def _extract_email(value: str) -> str:
    angle = re.search(r"<([^>]+)>", value)
    if angle:
        return angle.group(1).strip()

    plain = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", value)
    if plain:
        return plain.group(0).strip()

    return value.strip()


def _get_header_case_insensitive(headers: Dict[str, str], header_name: str) -> str:
    for key, value in headers.items():
        if key.lower() == header_name.lower():
            return value
    return ""


def _extract_body_contains(body_lines: List[str]) -> str:
    for raw_line in body_lines:
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("--"):
            continue
        lowered = line.lower()
        if lowered.startswith("mailcheckjwt:"):
            continue
        if lowered.startswith("mailchecksentat:"):
            continue
        return line
    return ""


def _normalize_template_name(path: str) -> str:
    stem = Path(path).stem
    ascii_stem = (
        unicodedata.normalize("NFKD", stem)
        .encode("ascii", "ignore")
        .decode("ascii")
        .lower()
    )
    normalized = re.sub(r"[^a-z0-9]+", "_", ascii_stem).strip("_")
    if not normalized:
        normalized = "mail_template"
    return normalized


def _format_env_value(value: str) -> str:
    if value == "":
        return ""
    if re.fullmatch(r"[A-Za-z0-9._/@:+-]+", value):
        return value
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _write_match_criteria_env_file(path: Path, values: Dict[str, str]) -> None:
    lines = [
        "# Match criteria",
        f"MAIL_SUBJECT_CONTAINS={_format_env_value(values['MAIL_SUBJECT_CONTAINS'])}",
        f"MAIL_FROM_CONTAINS={_format_env_value(values['MAIL_FROM_CONTAINS'])}",
        f"MAIL_BODY_CONTAINS={_format_env_value(values['MAIL_BODY_CONTAINS'])}",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def _set_default_active_config(env_path: Path, value: str) -> None:
    existing = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    lines = existing.splitlines()
    found = False
    updated: List[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("MAIL_ACTIVE_CONFIG="):
            updated.append(f"MAIL_ACTIVE_CONFIG={_format_env_value(value)}")
            found = True
        else:
            updated.append(line)

    if not found:
        if updated and updated[-1] != "":
            updated.append("")
        updated.append("# Optional default match criteria profile")
        updated.append(f"MAIL_ACTIVE_CONFIG={_format_env_value(value)}")

    env_path.write_text("\n".join(updated) + "\n", encoding="utf-8")


def _is_protected_settings_path(path: Path) -> bool:
    return path.resolve() == DEFAULT_ENV_PATH.resolve()


def _ensure_env_suffix(raw_value: str) -> str:
    candidate = raw_value.strip()
    if not candidate:
        return candidate
    if not candidate.endswith(".env"):
        return f"{candidate}.env"
    return candidate


def _path_for_env_reference(path: Path) -> str:
    try:
        relative = os.path.relpath(path, PROJECT_ROOT)
    except ValueError:
        return str(path.resolve())
    if relative.startswith(".."):
        return str(path.resolve())
    return relative


def _build_match_criteria_values(raw_headers: Dict[str, str], body_lines: List[str]) -> Dict[str, str]:
    subject = _get_header_case_insensitive(raw_headers, "Subject").strip()
    from_header = _get_header_case_insensitive(raw_headers, "From").strip()
    from_contains = _extract_email(from_header) if from_header else ""
    body_contains = _extract_body_contains(body_lines)
    if not subject:
        raise RuntimeError("template file has no Subject header.")

    return {
        "MAIL_SUBJECT_CONTAINS": subject,
        "MAIL_FROM_CONTAINS": from_contains,
        "MAIL_BODY_CONTAINS": body_contains,
    }


def _write_new_full_settings_from_example(target_path: Path, active_profile: str) -> None:
    if not DEFAULT_ENV_EXAMPLE_PATH.exists():
        raise RuntimeError(f"settings example not found: {DEFAULT_ENV_EXAMPLE_PATH}")
    lines = DEFAULT_ENV_EXAMPLE_PATH.read_text(encoding="utf-8").splitlines()

    found = False
    updated: List[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("MAIL_ACTIVE_CONFIG="):
            updated.append(f"MAIL_ACTIVE_CONFIG={_format_env_value(active_profile)}")
            found = True
        else:
            updated.append(line)

    if not found:
        if updated and updated[-1] != "":
            updated.append("")
        updated.append("# Optional default match criteria profile")
        updated.append(f"MAIL_ACTIVE_CONFIG={_format_env_value(active_profile)}")

    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text("\n".join(updated) + "\n", encoding="utf-8")


def _run_template_config_command(args: argparse.Namespace) -> int:
    template_path = _resolve_env_path(args.template_file)
    if not template_path.exists():
        print(f"ERROR - template file not found: {args.template_file} (resolved: {template_path})")
        return 3

    raw_headers, body_lines = _parse_template_sections(str(template_path))
    try:
        criteria_values = _build_match_criteria_values(raw_headers, body_lines)
    except RuntimeError as exc:
        print(f"ERROR - {exc}")
        return 3

    default_name = f"match_criteria_{_normalize_template_name(str(template_path))}.env"
    output_value = args.output.strip() if args.output else f"config/{default_name}"
    output_path = _resolve_env_path(_ensure_env_suffix(output_value))
    if _is_protected_settings_path(output_path):
        print(f"ERROR - protected file cannot be overwritten: {DEFAULT_ENV_PATH}")
        return 3

    if output_path.exists() and not args.force:
        print(f"ERROR - output file exists already: {output_path}")
        return 3

    _write_match_criteria_env_file(output_path, criteria_values)

    output_ref = _path_for_env_reference(output_path)
    print(f"OK - match criteria config created: {output_path}")
    print(f"Template subject -> MAIL_SUBJECT_CONTAINS: {criteria_values['MAIL_SUBJECT_CONTAINS']}")
    if criteria_values["MAIL_FROM_CONTAINS"]:
        print(f"Template from -> MAIL_FROM_CONTAINS: {criteria_values['MAIL_FROM_CONTAINS']}")
    if criteria_values["MAIL_BODY_CONTAINS"]:
        print(f"Template body -> MAIL_BODY_CONTAINS: {criteria_values['MAIL_BODY_CONTAINS']}")

    if args.new_config:
        new_config_candidate = _ensure_env_suffix(args.new_config.strip())
        if "/" not in new_config_candidate:
            new_config_candidate = f"config/{new_config_candidate}"
        new_config_path = _resolve_env_path(new_config_candidate)
        if _is_protected_settings_path(new_config_path):
            print(f"ERROR - protected file cannot be overwritten: {DEFAULT_ENV_PATH}")
            return 3
        if new_config_path.exists():
            print(f"ERROR - new config file exists already: {new_config_path}")
            return 3
        _write_new_full_settings_from_example(new_config_path, output_ref)
        print(f"OK - full settings config created from example: {new_config_path}")

    if args.set_default:
        _set_default_active_config(DEFAULT_ENV_PATH, output_ref)
        print(f"Default profile set in {DEFAULT_ENV_PATH}: MAIL_ACTIVE_CONFIG={output_ref}")

    return 0


def find_matching_message_ids(args: argparse.Namespace) -> Tuple[List[bytes], str]:
    ctx = ssl.create_default_context()
    imap = imaplib.IMAP4_SSL(args.imap_host, args.imap_port, ssl_context=ctx)
    try:
        imap.login(args.imap_user, args.imap_password)
        status, _ = imap.select(args.mailbox)
        if status != "OK":
            raise RuntimeError(f"Cannot select mailbox {args.mailbox!r}")

        criteria: List[str] = []
        if not args.include_seen:
            criteria.append("UNSEEN")
        if args.subject_contains:
            criteria.extend(["HEADER", "Subject", _decode_header_val(args.subject_contains)])
        if args.from_contains:
            criteria.extend(["HEADER", "From", _decode_header_val(args.from_contains)])
        if args.body_contains:
            criteria.extend(["BODY", _decode_header_val(args.body_contains)])
        if not criteria:
            criteria = ["ALL"]

        status, data = imap.search(None, *criteria)
        if status != "OK":
            raise RuntimeError("IMAP SEARCH failed")

        msg_ids = data[0].split() if data and data[0] else []

        return msg_ids, " ".join(criteria)
    finally:
        try:
            imap.close()
        except Exception:
            pass
        imap.logout()


def _extract_body_text(message) -> str:
    if message.is_multipart():
        text_parts: List[str] = []
        for part in message.walk():
            if part.get_content_maintype() != "text":
                continue
            if part.get_content_disposition() == "attachment":
                continue
            try:
                text_parts.append(part.get_content())
            except Exception:
                payload = part.get_payload(decode=True) or b""
                text_parts.append(payload.decode("utf-8", errors="replace"))
        return "\n".join(text_parts)

    try:
        return message.get_content()
    except Exception:
        payload = message.get_payload(decode=True) or b""
        return payload.decode("utf-8", errors="replace")


def _parse_mailcheck_timestamp(value: str) -> Optional[datetime]:
    cleaned = value.strip()
    if not cleaned:
        return None
    try:
        if cleaned.endswith("Z"):
            cleaned = cleaned[:-1] + "+00:00"
        parsed = datetime.fromisoformat(cleaned)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _extract_mailcheck_meta(message) -> Tuple[str, Optional[datetime]]:
    header_token = (message.get("X-Mail-Check-Jwt") or "").strip()
    header_sent_at = (message.get("X-Mail-Check-Sent-At") or "").strip()
    sent_at = _parse_mailcheck_timestamp(header_sent_at)

    body = _extract_body_text(message)
    body_token = ""
    token_match = re.search(r"(?im)^MailCheckJwt:\s*(.+?)\s*$", body)
    if token_match:
        body_token = token_match.group(1).strip()

    sent_match = re.search(r"(?im)^MailCheckSentAt:\s*(.+?)\s*$", body)
    if sent_match and not sent_at:
        sent_at = _parse_mailcheck_timestamp(sent_match.group(1))

    token = header_token or body_token
    return token, sent_at


def _extract_received_timestamp(message) -> Optional[datetime]:
    for received in message.get_all("Received", []):
        candidate = received.rsplit(";", 1)[-1].strip() if ";" in received else received.strip()
        if not candidate:
            continue
        try:
            parsed = parsedate_to_datetime(candidate)
        except (TypeError, ValueError):
            continue
        if parsed is None:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return None


def _collect_valid_matches(
    args: argparse.Namespace, msg_ids: List[bytes]
) -> Tuple[List[bytes], Dict[str, Optional[float]]]:
    if not msg_ids:
        return [], {
            "mail_delivery_seconds": None,
            "send_to_delivery_seconds": None,
            "delivery_to_check_seconds": None,
        }

    ctx = ssl.create_default_context()
    imap = imaplib.IMAP4_SSL(args.imap_host, args.imap_port, ssl_context=ctx)
    now_utc = datetime.now(timezone.utc)
    valid_ids: List[bytes] = []
    metrics: Dict[str, Optional[float]] = {
        "mail_delivery_seconds": None,
        "send_to_delivery_seconds": None,
        "delivery_to_check_seconds": None,
    }

    try:
        imap.login(args.imap_user, args.imap_password)
        status, _ = imap.select(args.mailbox)
        if status != "OK":
            raise RuntimeError(f"Cannot select mailbox {args.mailbox!r}")

        for msg_id in reversed(msg_ids):
            fetch_status, fetch_data = imap.fetch(msg_id, "(RFC822)")
            if fetch_status != "OK" or not fetch_data:
                continue

            raw_email = b""
            for chunk in fetch_data:
                if isinstance(chunk, tuple) and len(chunk) > 1 and isinstance(chunk[1], (bytes, bytearray)):
                    raw_email = bytes(chunk[1])
                    break
            if not raw_email:
                continue

            message = BytesParser(policy=policy.default).parsebytes(raw_email)
            message_token, sent_at = _extract_mailcheck_meta(message)
            try:
                jwt_issued_at = _verify_mailcheck_jwt(
                    token=message_token,
                    secret=args.mail_jwt_secret,
                    max_age_seconds=args.mail_jwt_max_age_seconds,
                )
            except Exception:
                continue

            valid_ids.append(msg_id)
            if metrics["mail_delivery_seconds"] is None:
                received_at = _extract_received_timestamp(message)
                end_to_end = max(0.0, (now_utc - jwt_issued_at).total_seconds())
                metrics["mail_delivery_seconds"] = end_to_end

                if received_at:
                    send_to_delivery = max(0.0, (received_at - jwt_issued_at).total_seconds())
                    delivery_to_check = max(0.0, (now_utc - received_at).total_seconds())
                    metrics["send_to_delivery_seconds"] = send_to_delivery
                    metrics["delivery_to_check_seconds"] = delivery_to_check

        if args.delete_match and valid_ids:
            for valid_id in valid_ids:
                imap.store(valid_id, "+FLAGS", "\\Deleted")
            imap.expunge()

        return valid_ids, metrics
    finally:
        try:
            imap.close()
        except Exception:
            pass
        imap.logout()


def _normalize_api_code(value: object) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _split_plugin_output_and_perfdata(output: str) -> Tuple[str, List[str]]:
    if "|" not in output:
        return output.strip(), []
    plugin_output, perfdata_raw = output.split("|", 1)
    perf_items = [item.strip() for item in perfdata_raw.strip().split() if item.strip()]
    return plugin_output.strip(), perf_items


def _build_icinga_submit(endpoint: str, args: argparse.Namespace, exit_status: int, output: str) -> Tuple[dict, dict]:
    plugin_output, performance_data = _split_plugin_output_and_perfdata(output)
    payload = {
        "type": "Service",
        "filter": f'host.name=="{args.icinga_host}" && service.name=="{args.icinga_service}"',
        "exit_status": exit_status,
        "plugin_output": plugin_output,
    }
    if performance_data:
        payload["performance_data"] = performance_data
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": "Basic "
        + (
            __import__("base64")
            .b64encode(f"{args.icinga_user}:{args.icinga_password}".encode("utf-8"))
            .decode("ascii")
        ),
    }
    return payload, headers


def _build_curl_command(endpoint: str, args: argparse.Namespace, payload: dict) -> str:
    payload_json = json.dumps(payload, ensure_ascii=False)
    insecure = "--insecure " if not args.icinga_verify_tls else ""
    return (
        f"curl -sS -X POST {insecure}"
        f"-u {shlex.quote(f'{args.icinga_user}:{args.icinga_password}')} "
        f"-H 'Accept: application/json' "
        f"-H 'Content-Type: application/json' "
        f"{shlex.quote(endpoint)} "
        f"-d {shlex.quote(payload_json)}"
    )


def submit_passive_result(args: argparse.Namespace, exit_status: int, output: str) -> str:
    endpoint = args.icinga_url.rstrip("/") + "/v1/actions/process-check-result"
    payload, headers = _build_icinga_submit(endpoint, args, exit_status, output)

    if args.debug_icinga:
        split_output, split_perfdata = _split_plugin_output_and_perfdata(output)
        print("Icinga endpoint:", endpoint)
        print("Icinga plugin_output:", split_output)
        print("Icinga performance_data:", split_perfdata if split_perfdata else "[]")
        print("Icinga payload:", json.dumps(payload, ensure_ascii=False))
        print("Icinga curl:", _build_curl_command(endpoint, args, payload))
        if args.icinga_dry_run:
            return "dry-run: submit skipped"

    req = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers=headers,
    )

    context = ssl.create_default_context() if args.icinga_verify_tls else ssl._create_unverified_context()

    try:
        with urllib.request.urlopen(req, timeout=15, context=context) as resp:
            response_body = resp.read().decode("utf-8", errors="replace")
            if resp.status < 200 or resp.status >= 300:
                raise RuntimeError(f"Icinga API returned status {resp.status}: {response_body}")
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Failed to submit passive result to Icinga: {exc}") from exc

    try:
        data = json.loads(response_body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Icinga API returned invalid JSON: {response_body[:200]}") from exc

    results = data.get("results", [])
    if not results:
        raise RuntimeError(
            "Icinga API returned no results. Check ICINGA_HOST/ICINGA_SERVICE and API permissions."
        )

    bad_results = [r for r in results if _normalize_api_code(r.get("code")) >= 300]
    if bad_results:
        statuses = "; ".join(str(r.get("status", "unknown error")) for r in bad_results)
        raise RuntimeError(f"Icinga API rejected check result: {statuses}")

    return "; ".join(str(r.get("status", "ok")) for r in results)


def _missing_icinga_args(args: argparse.Namespace) -> List[str]:
    missing: List[str] = []
    if not args.icinga_url:
        missing.append("ICINGA_URL/--icinga-url")
    if not args.icinga_user:
        missing.append("ICINGA_USER/--icinga-user")
    if not args.icinga_password:
        missing.append("ICINGA_PASSWORD/--icinga-password")
    if not args.icinga_host:
        missing.append("ICINGA_HOST/--icinga-host")
    if not args.icinga_service:
        missing.append("ICINGA_SERVICE/--icinga-service")
    return missing


def _build_send_message(args: argparse.Namespace) -> EmailMessage:
    sent_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    jwt_value = _create_mailcheck_jwt(args.mail_jwt_secret, datetime.now(timezone.utc))
    body = f"MailCheckJwt: {jwt_value}\nMailCheckSentAt: {sent_at}\n\n{args.send_body}"

    message = EmailMessage()
    message["From"] = args.send_from
    message["To"] = args.send_to
    message["Subject"] = args.send_subject
    message["X-Mail-Check-Jwt"] = jwt_value
    message["X-Mail-Check-Sent-At"] = sent_at
    message.set_content(body)
    return message


def _send_via_sendmail(args: argparse.Namespace, message: EmailMessage) -> None:
    command = shlex.split(args.sendmail_command)
    if not command:
        raise RuntimeError("MAIL_SEND_SENDMAIL_COMMAND is empty.")
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


def _send_via_mail_cmd(args: argparse.Namespace) -> None:
    sent_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    jwt_value = _create_mailcheck_jwt(args.mail_jwt_secret, datetime.now(timezone.utc))
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


def _send_via_smtp(args: argparse.Namespace, message: EmailMessage) -> None:
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


def _run_send_command(args: argparse.Namespace) -> int:
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

    message = _build_send_message(args)
    started = time.perf_counter()
    try:
        if args.send_backend == "sendmail":
            _send_via_sendmail(args, message)
        elif args.send_backend == "mail":
            _send_via_mail_cmd(args)
        elif args.send_backend == "smtp":
            _send_via_smtp(args, message)
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


def _run_email_check(args: argparse.Namespace) -> Tuple[int, str]:
    if not args.mail_jwt_secret:
        return 3, "UNKNOWN - MAIL_CHECK_JWT_SECRET is required for mail validation."

    try:
        msg_ids, criteria = find_matching_message_ids(args)
    except Exception as exc:
        return 3, f"UNKNOWN - mailbox poll failed: {exc}"

    if not msg_ids:
        return 2, f"CRITICAL - no matching mail found; criteria=[{criteria}]"

    try:
        valid_ids, metrics = _collect_valid_matches(args, msg_ids)
    except Exception as exc:
        return 3, f"UNKNOWN - mailbox validation failed: {exc}"

    if valid_ids:
        send_to_delivery_text = (
            f"{metrics['send_to_delivery_seconds']:.3f}"
            if metrics["send_to_delivery_seconds"] is not None
            else "n/a"
        )
        delivery_to_check_text = (
            f"{metrics['delivery_to_check_seconds']:.3f}"
            if metrics["delivery_to_check_seconds"] is not None
            else "n/a"
        )
        end_to_end_text = (
            f"{metrics['mail_delivery_seconds']:.3f}" if metrics["mail_delivery_seconds"] is not None else "n/a"
        )
        perfdata_parts: List[str] = []
        if metrics["send_to_delivery_seconds"] is not None:
            perfdata_parts.append(f"send_to_delivery_seconds={metrics['send_to_delivery_seconds']:.3f}s;;;;")
        if metrics["delivery_to_check_seconds"] is not None:
            perfdata_parts.append(f"delivery_to_check_seconds={metrics['delivery_to_check_seconds']:.3f}s;;;;")
        if metrics["mail_delivery_seconds"] is not None:
            perfdata_parts.append(f"mail_delivery_seconds={metrics['mail_delivery_seconds']:.3f}s;;;;")
        perfdata = f" | {' '.join(perfdata_parts)}" if perfdata_parts else ""
        return (
            0,
            f"Mail Check OK: expected mail found ({len(valid_ids)} valid match(es)) - "
            f"send_to_delivery_seconds={send_to_delivery_text} "
            f"delivery_to_check_seconds={delivery_to_check_text} "
            f"mail_delivery_seconds={end_to_end_text}{perfdata}",
        )
    return 2, f"CRITICAL - matching mail found but token check failed; criteria=[{criteria}]"


def _run_check_command(args: argparse.Namespace) -> int:
    exit_code, output = _run_email_check(args)
    if args.no_icinga_submit or not args.icinga_passive_check:
        print(output)
        return exit_code

    missing = _missing_icinga_args(args)
    if missing:
        print(f"UNKNOWN - Icinga settings missing: {', '.join(missing)}")
        return 3

    try:
        submit_status = submit_passive_result(args, exit_code, output)
        print(f"Icinga submit OK - {submit_status}")
    except Exception as exc:
        print(f"UNKNOWN - Icinga submit failed: {exc}")
        return 3

    print(output)
    return exit_code


def _run_icinga_command(args: argparse.Namespace) -> int:
    missing = _missing_icinga_args(args)
    if missing:
        print(f"UNKNOWN - Icinga settings missing: {', '.join(missing)}")
        return 3

    try:
        submit_status = submit_passive_result(args, args.test_exit_status, args.test_output)
        print(f"Icinga submit OK - {submit_status}")
    except Exception as exc:
        print(f"UNKNOWN - Icinga submit failed: {exc}")
        return 3

    print(
        f"TEST - icinga command submitted test payload "
        f"(exit_status={args.test_exit_status}, output={args.test_output!r})"
    )
    return 0


def _ensure_active_profile_required(args: argparse.Namespace) -> int:
    if args.command in {"template-config", "send"}:
        return 0
    active_profile = os.getenv("MAIL_ACTIVE_CONFIG", "").strip()
    if active_profile:
        return 0
    print("ERROR - MAIL_ACTIVE_CONFIG is required in settings config or via --config.")
    return 3


def main() -> int:
    bootstrap = argparse.ArgumentParser(add_help=False)
    bootstrap.add_argument("--config", "-c", default="")
    bootstrap_args, remaining_args = bootstrap.parse_known_args()
    help_requested = any(token in {"-h", "--help"} for token in remaining_args)
    requested_command = ""
    for token in remaining_args:
        if token in {"check", "email", "icinga", "send", "template-config"}:
            requested_command = token
            break
    require_active_profile = requested_command in {"check", "email", "icinga"} and not help_requested

    runtime_warning = ""
    try:
        runtime_warning = load_runtime_env(
            config_override=bootstrap_args.config,
            require_active_profile=require_active_profile,
        )
    except Exception as exc:
        print(f"ERROR - failed to load runtime config: {exc}")
        return 3

    parser = build_parser()
    args = parser.parse_args()
    if args.print_cron_line:
        print(build_cron_line())
        return 0

    if not args.command:
        if runtime_warning:
            print(f"HINWEIS - {runtime_warning}")
        parser.print_help()
        return 0

    profile_check_code = _ensure_active_profile_required(args)
    if profile_check_code != 0:
        return profile_check_code

    if args.command == "check":
        return _run_check_command(args)

    if args.command == "email":
        exit_code, output = _run_email_check(args)
        print(output)
        return exit_code

    if args.command == "icinga":
        return _run_icinga_command(args)

    if args.command == "send":
        return _run_send_command(args)

    if args.command == "template-config":
        return _run_template_config_command(args)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
