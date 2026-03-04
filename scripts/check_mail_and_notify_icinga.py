#!/usr/bin/env python3
import argparse
import re
import shlex
import imaplib
import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from typing import Dict, List, Tuple


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Poll IMAP mailbox for expected message, optionally delete it, "
            "then optionally submit passive result to Icinga2 API."
        )
    )

    p.add_argument("--imap-host", default=os.getenv("IMAP_HOST"), required=not os.getenv("IMAP_HOST"))
    p.add_argument("--imap-port", type=int, default=int(os.getenv("IMAP_PORT", "993")))
    p.add_argument("--imap-user", default=os.getenv("IMAP_USER"), required=not os.getenv("IMAP_USER"))
    p.add_argument("--imap-password", default=os.getenv("IMAP_PASSWORD"), required=not os.getenv("IMAP_PASSWORD"))
    p.add_argument("--mailbox", default=os.getenv("IMAP_MAILBOX", "INBOX"))

    p.add_argument("--subject-contains", default=os.getenv("MAIL_SUBJECT_CONTAINS", ""))
    p.add_argument("--from-contains", default=os.getenv("MAIL_FROM_CONTAINS", ""))
    p.add_argument("--header-template-file", default=os.getenv("MAIL_HEADER_TEMPLATE_FILE", ""))
    p.add_argument(
        "--template-headers",
        default=os.getenv("MAIL_TEMPLATE_HEADERS", "Subject,From,To,Return-Path,X-KasLoop"),
        help="Comma-separated header names to load from --header-template-file",
    )
    p.add_argument("--include-seen", action="store_true", default=os.getenv("MAIL_INCLUDE_SEEN", "0") == "1")
    p.add_argument("--delete-match", action="store_true", default=os.getenv("MAIL_DELETE_MATCH", "0") == "1")

    p.add_argument("--notify-icinga", dest="notify_icinga", action="store_true")
    p.add_argument("--no-notify-icinga", dest="notify_icinga", action="store_false")
    p.set_defaults(notify_icinga=os.getenv("MAIL_NOTIFY_ICINGA", "1") == "1")

    p.add_argument("--icinga-url", default=os.getenv("ICINGA_URL"))
    p.add_argument("--icinga-user", default=os.getenv("ICINGA_USER"))
    p.add_argument("--icinga-password", default=os.getenv("ICINGA_PASSWORD"))
    p.add_argument("--icinga-host", default=os.getenv("ICINGA_HOST"))
    p.add_argument("--icinga-service", default=os.getenv("ICINGA_SERVICE"))
    p.add_argument("--icinga-verify-tls", action="store_true", default=os.getenv("ICINGA_VERIFY_TLS", "1") == "1")
    p.add_argument("--debug-icinga", action="store_true", default=os.getenv("MAIL_DEBUG_ICINGA", "0") == "1")
    p.add_argument("--icinga-dry-run", action="store_true", default=os.getenv("MAIL_ICINGA_DRY_RUN", "0") == "1")

    return p.parse_args()


def _decode_header_val(value: str) -> str:
    # For IMAP SEARCH, keep criteria simple and ASCII-safe.
    return value.encode("ascii", errors="ignore").decode("ascii")


def _parse_raw_headers(path: str) -> Dict[str, str]:
    headers: Dict[str, str] = {}
    current_name = ""
    current_value_parts: List[str] = []

    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for raw_line in f:
            line = raw_line.rstrip("\r\n")
            if not line:
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

    if current_name:
        headers[current_name] = " ".join(current_value_parts).strip()

    return headers


def _extract_email(value: str) -> str:
    angle = re.search(r"<([^>]+)>", value)
    if angle:
        return angle.group(1).strip()

    plain = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", value)
    if plain:
        return plain.group(0).strip()

    return value.strip()


def _normalize_header_value(header_name: str, value: str) -> str:
    name = header_name.lower()
    if name in {"from", "to", "return-path", "reply-to", "sender"}:
        return _extract_email(value)
    return value.strip()


def _collect_template_header_filters(args: argparse.Namespace) -> List[Tuple[str, str]]:
    if not args.header_template_file:
        return []

    raw_headers = _parse_raw_headers(args.header_template_file)
    wanted = [h.strip() for h in args.template_headers.split(",") if h.strip()]
    lower_map = {k.lower(): k for k in raw_headers.keys()}

    selected: List[Tuple[str, str]] = []
    for header_name in wanted:
        raw_key = lower_map.get(header_name.lower())
        if not raw_key:
            continue
        value = _normalize_header_value(raw_key, raw_headers[raw_key])
        if value:
            selected.append((raw_key, value))

    return selected


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
        for header_name, header_value in _collect_template_header_filters(args):
            criteria.extend(["HEADER", header_name, _decode_header_val(header_value)])
        if not criteria:
            criteria = ["ALL"]

        status, data = imap.search(None, *criteria)
        if status != "OK":
            raise RuntimeError("IMAP SEARCH failed")

        msg_ids = data[0].split() if data and data[0] else []

        if msg_ids and args.delete_match:
            for msg_id in msg_ids:
                imap.store(msg_id, "+FLAGS", "\\Deleted")
            imap.expunge()

        return msg_ids, " ".join(criteria)
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


def _build_icinga_submit(endpoint: str, args: argparse.Namespace, exit_status: int, output: str) -> Tuple[dict, dict]:
    payload = {
        "type": "Service",
        "filter": f'host.name=="{args.icinga_host}" && service.name=="{args.icinga_service}"',
        "exit_status": exit_status,
        "plugin_output": output,
    }
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
        print("Icinga endpoint:", endpoint)
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


def main() -> int:
    args = parse_args()
    if args.notify_icinga:
        missing = _missing_icinga_args(args)
        if missing:
            print(f"UNKNOWN - Icinga notification enabled but missing settings: {', '.join(missing)}")
            return 3

    try:
        msg_ids, criteria = find_matching_message_ids(args)
    except Exception as exc:
        error_output = f"UNKNOWN - mailbox poll failed: {exc}"
        if args.notify_icinga:
            try:
                submit_passive_result(args, 3, error_output)
            except Exception as notify_exc:
                print(f"WARN - could not submit mailbox error to Icinga: {notify_exc}")
        print(error_output)
        return 3

    if msg_ids:
        output = (
            f"OK - expected mail found ({len(msg_ids)} match(es)); "
            f"criteria=[{criteria}]; delete_match={args.delete_match}"
        )
        exit_code = 0
    else:
        output = f"CRITICAL - no matching mail found; criteria=[{criteria}]"
        exit_code = 2

    if args.notify_icinga:
        try:
            submit_status = submit_passive_result(args, exit_code, output)
            print(f"Icinga submit OK - {submit_status}")
        except Exception as exc:
            print(f"UNKNOWN - Icinga submit failed: {exc}")
            return 3

    print(output)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
