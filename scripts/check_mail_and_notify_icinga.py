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
import unicodedata
from pathlib import Path
from typing import Dict, List, Tuple

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
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


def load_runtime_env(config_override: str = "") -> None:
    load_dotenv(dotenv_path=DEFAULT_ENV_PATH, override=False)

    selected_config = config_override.strip() if config_override else ""
    if selected_config:
        selected_path = _resolve_env_path(selected_config)
        if not selected_path.exists():
            raise RuntimeError(
                f"Configured env file not found: {selected_config} (resolved: {selected_path})"
            )
        selected_active_profile = _read_env_key(selected_path, "MAIL_ACTIVE_CONFIG")
        if not selected_active_profile:
            raise RuntimeError(
                f"Configured env file must define non-empty MAIL_ACTIVE_CONFIG: {selected_path}"
            )
        load_dotenv(dotenv_path=selected_path, override=True)

    active_profile = os.getenv("MAIL_ACTIVE_CONFIG", "").strip()
    if not active_profile:
        return

    profile_path = _resolve_env_path(active_profile)
    if not profile_path.exists():
        raise RuntimeError(
            f"Configured active profile not found: {active_profile} (resolved: {profile_path})"
        )
    load_dotenv(dotenv_path=profile_path, override=True)


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Mailbox check and optional Icinga2 submit via subcommands. "
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

    check_parser = subparsers.add_parser("check", help="Check mailbox and submit result to Icinga.")
    _add_mail_args(check_parser)
    _add_icinga_args(check_parser)

    email_parser = subparsers.add_parser("email", help="Check mailbox only, no Icinga submit.")
    _add_mail_args(email_parser)

    icinga_parser = subparsers.add_parser("icinga", help="Submit test result to Icinga only.")
    _add_icinga_args(icinga_parser)
    icinga_parser.add_argument(
        "--test-exit-status",
        type=int,
        default=0,
        help="Exit status to submit for icinga test command.",
    )
    icinga_parser.add_argument(
        "--test-output",
        default="OK - Icinga test only (no mailbox check).",
        help="Plugin output text for icinga test command.",
    )

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
    # For IMAP SEARCH, keep criteria simple and ASCII-safe.
    return value.encode("ascii", errors="ignore").decode("ascii")


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


def _run_email_check(args: argparse.Namespace) -> Tuple[int, str]:
    try:
        msg_ids, criteria = find_matching_message_ids(args)
    except Exception as exc:
        return 3, f"UNKNOWN - mailbox poll failed: {exc}"

    if msg_ids:
        return (
            0,
            f"OK - expected mail found ({len(msg_ids)} match(es)); criteria=[{criteria}]; delete_match={args.delete_match}",
        )
    return 2, f"CRITICAL - no matching mail found; criteria=[{criteria}]"


def _run_check_command(args: argparse.Namespace) -> int:
    missing = _missing_icinga_args(args)
    if missing:
        print(f"UNKNOWN - Icinga settings missing: {', '.join(missing)}")
        return 3

    exit_code, output = _run_email_check(args)
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
    if args.command == "template-config":
        return 0
    active_profile = os.getenv("MAIL_ACTIVE_CONFIG", "").strip()
    if active_profile:
        return 0
    print("ERROR - MAIL_ACTIVE_CONFIG is required in settings config or via --config.")
    return 3


def main() -> int:
    bootstrap = argparse.ArgumentParser(add_help=False)
    bootstrap.add_argument("--config", "-c", default="")
    bootstrap_args, _ = bootstrap.parse_known_args()
    try:
        load_runtime_env(config_override=bootstrap_args.config)
    except Exception as exc:
        print(f"ERROR - failed to load runtime config: {exc}")
        return 3

    parser = build_parser()
    args = parser.parse_args()
    if args.print_cron_line:
        print(build_cron_line())
        return 0

    if not args.command:
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

    if args.command == "template-config":
        return _run_template_config_command(args)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
