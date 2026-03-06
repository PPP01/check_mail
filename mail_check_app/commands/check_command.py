import imaplib
import re
import ssl
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
from email.utils import parsedate_to_datetime
from typing import Dict, List, Optional, Tuple

from ..shared.icinga_api import missing_icinga_args, submit_passive_result
from ..shared.jwt_utils import parse_mailcheck_timestamp, validate_mailcheck_secret, verify_mailcheck_jwt


def decode_header_val(value: str) -> str:
    """Dekodiert einen Header-Wert für die IMAP-Suche und maskiert Sonderzeichen."""
    safe = value.encode("ascii", errors="ignore").decode("ascii")
    escaped = safe.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def find_matching_message_ids(args, imap: imaplib.IMAP4_SSL) -> Tuple[List[bytes], str]:
    """Durchsucht das IMAP-Postfach nach Nachrichten, die den Kriterien entsprechen."""
    status, _ = imap.select(args.mailbox)
    if status != "OK":
        raise RuntimeError(f"Postfach {args.mailbox!r} konnte nicht ausgewählt werden")

    criteria: List[str] = []
    if not args.include_seen:
        criteria.append("UNSEEN")
    if args.subject_contains:
        criteria.extend(["HEADER", "Subject", decode_header_val(args.subject_contains)])
    if args.from_contains:
        criteria.extend(["HEADER", "From", decode_header_val(args.from_contains)])
    if args.body_contains:
        criteria.extend(["BODY", decode_header_val(args.body_contains)])
    if not criteria:
        criteria = ["ALL"]

    status, data = imap.search(None, *criteria)
    if status != "OK":
        raise RuntimeError("IMAP-Suche fehlgeschlagen")

    msg_ids = data[0].split() if data and data[0] else []
    return msg_ids, " ".join(criteria)


def extract_body_text(message) -> str:
    """Extrahiert den Textinhalt (Plaintext) aus einer E-Mail-Nachricht."""
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


def extract_mailcheck_meta(message) -> Tuple[str, Optional[datetime]]:
    """Extrahiert das JWT und den Sende-Zeitstempel aus den Headern oder dem Body."""
    header_token = (message.get("X-Mail-Check-Jwt") or "").strip()
    header_sent_at = (message.get("X-Mail-Check-Sent-At") or "").strip()
    sent_at = parse_mailcheck_timestamp(header_sent_at)

    body = extract_body_text(message)
    body_token = ""
    token_match = re.search(r"(?im)^MailCheckJwt:\s*(.+?)\s*$", body)
    if token_match:
        body_token = token_match.group(1).strip()

    sent_match = re.search(r"(?im)^MailCheckSentAt:\s*(.+?)\s*$", body)
    if sent_match and not sent_at:
        sent_at = parse_mailcheck_timestamp(sent_match.group(1))

    token = header_token or body_token
    return token, sent_at


def extract_received_timestamp(message) -> Optional[datetime]:
    """Ermittelt den Empfangszeitstempel aus den 'Received'-Headern der E-Mail."""
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


def collect_valid_matches(
    args, imap: imaplib.IMAP4_SSL, msg_ids: List[bytes]
) -> Tuple[List[bytes], Dict[str, Optional[float]]]:
    """Validiert JWTs für Kandidaten-Mails und berechnet Zustellungs-Metriken."""
    if not msg_ids:
        return [], {
            "mail_delivery_seconds": None,
            "send_to_delivery_seconds": None,
            "delivery_to_check_seconds": None,
        }

    now_utc = datetime.now(timezone.utc)
    valid_ids: List[bytes] = []
    metrics: Dict[str, Optional[float]] = {
        "mail_delivery_seconds": None,
        "send_to_delivery_seconds": None,
        "delivery_to_check_seconds": None,
    }

    status, _ = imap.select(args.mailbox)
    if status != "OK":
        raise RuntimeError(f"Postfach {args.mailbox!r} konnte nicht ausgewählt werden")

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
        message_token, _ = extract_mailcheck_meta(message)
        try:
            jwt_issued_at = verify_mailcheck_jwt(
                token=message_token,
                secret=args.mail_jwt_secret,
            )

        except RuntimeError:
            continue

        valid_ids.append(msg_id)
        if metrics["mail_delivery_seconds"] is None:
            received_at = extract_received_timestamp(message)
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
        if not getattr(args, "soft_delete_match", False):
            imap.expunge()

    return valid_ids, metrics


def run_email_check(args) -> Tuple[int, str]:
    """Führt die Postfach-Validierung durch und gibt Exit-Code und Nagios-Output zurück."""
    if not args.mail_jwt_secret:
        return 3, "UNKNOWN - MAIL_CHECK_JWT_SECRET ist für die Validierung erforderlich."
    try:
        validate_mailcheck_secret(args.mail_jwt_secret)
    except RuntimeError as exc:
        return 3, f"UNKNOWN - {exc}"

    ctx = ssl.create_default_context()
    imap = imaplib.IMAP4_SSL(args.imap_host, args.imap_port, ssl_context=ctx)
    try:
        imap.login(args.imap_user, args.imap_password)

        try:
            msg_ids, criteria = find_matching_message_ids(args, imap)
        except Exception as exc:
            return 3, f"UNKNOWN - Postfach-Abfrage fehlgeschlagen: {exc}"

        if not msg_ids:
            return 2, f"CRITICAL - keine passende Mail gefunden; Kriterien=[{criteria}]"

        try:
            valid_ids, metrics = collect_valid_matches(args, imap, msg_ids)
        except Exception as exc:
            return 3, f"UNKNOWN - Postfach-Validierung fehlgeschlagen: {exc}"

    finally:
        try:
            imap.close()
        except Exception:
            pass
        imap.logout()

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
            f"Mail Check OK: Passende Mail gefunden ({len(valid_ids)} gültige Treffer) - "
            f"send_to_delivery_seconds={send_to_delivery_text} "
            f"delivery_to_check_seconds={delivery_to_check_text} "
            f"mail_delivery_seconds={end_to_end_text}{perfdata}",
        )
    return 2, "CRITICAL - passende Mail gefunden, aber JWT-Validierung fehlgeschlagen (ungültige Signatur oder abgelaufen)."


def run_check_command(args) -> int:
    """Führt 'check' aus und übermittelt das Ergebnis optional passiv an Icinga."""
    exit_code, output = run_email_check(args)
    if args.no_icinga_submit or not args.icinga_passive_check:
        print(output)
        return exit_code

    missing = missing_icinga_args(args)
    if missing:
        print(f"UNKNOWN - Icinga-Einstellungen fehlen: {', '.join(missing)}")
        return 3

    try:
        submit_status = submit_passive_result(args, exit_code, output)
        print(f"Icinga submit OK - {submit_status}")
    except Exception as exc:
        print(f"UNKNOWN - Icinga submit fehlgeschlagen: {exc}")
        return 3

    print(output)
    return exit_code
