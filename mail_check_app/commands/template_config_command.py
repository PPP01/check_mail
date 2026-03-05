import os
import re
import unicodedata
from email import policy
from email.parser import BytesParser
from pathlib import Path
from typing import Dict, List, Tuple

from ..runtime import DEFAULT_ENV_EXAMPLE_PATH, DEFAULT_ENV_PATH, PROJECT_ROOT, resolve_env_path


def extract_body_text(message) -> str:
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


def parse_template_sections(path: str) -> Tuple[Dict[str, str], List[str]]:
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

    try:
        with open(path, "rb") as f:
            message = BytesParser(policy=policy.default).parse(f)
        parsed_body = extract_body_text(message).splitlines()
        if any(line.strip() for line in parsed_body):
            body_lines = parsed_body
    except Exception:
        pass

    return headers, body_lines


def extract_email(value: str) -> str:
    angle = re.search(r"<([^>]+)>", value)
    if angle:
        return angle.group(1).strip()

    plain = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", value)
    if plain:
        return plain.group(0).strip()

    return value.strip()


def get_header_case_insensitive(headers: Dict[str, str], header_name: str) -> str:
    for key, value in headers.items():
        if key.lower() == header_name.lower():
            return value
    return ""


def extract_body_contains(body_lines: List[str]) -> str:
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


def normalize_template_name(path: str) -> str:
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


def format_env_value(value: str) -> str:
    if value == "":
        return ""
    if re.fullmatch(r"[A-Za-z0-9._/@:+-]+", value):
        return value
    return "'" + value.replace("'", "'\"'\"'") + "'"


def write_match_criteria_env_file(path: Path, values: Dict[str, str]) -> None:
    lines = [
        "# Match criteria",
        f"MAIL_SUBJECT_CONTAINS={format_env_value(values['MAIL_SUBJECT_CONTAINS'])}",
        f"MAIL_FROM_CONTAINS={format_env_value(values['MAIL_FROM_CONTAINS'])}",
        f"MAIL_BODY_CONTAINS={format_env_value(values['MAIL_BODY_CONTAINS'])}",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def set_default_active_config(env_path: Path, value: str) -> None:
    existing = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    lines = existing.splitlines()
    found = False
    updated: List[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("MAIL_ACTIVE_CONFIG="):
            updated.append(f"MAIL_ACTIVE_CONFIG={format_env_value(value)}")
            found = True
        else:
            updated.append(line)

    if not found:
        if updated and updated[-1] != "":
            updated.append("")
        updated.append("# Optional default match criteria profile")
        updated.append(f"MAIL_ACTIVE_CONFIG={format_env_value(value)}")

    env_path.write_text("\n".join(updated) + "\n", encoding="utf-8")


def is_protected_settings_path(path: Path) -> bool:
    return path.resolve() == DEFAULT_ENV_PATH.resolve()


def ensure_env_suffix(raw_value: str) -> str:
    candidate = raw_value.strip()
    if not candidate:
        return candidate
    if not candidate.endswith(".env"):
        return f"{candidate}.env"
    return candidate


def path_for_env_reference(path: Path) -> str:
    try:
        relative = os.path.relpath(path, PROJECT_ROOT)
    except ValueError:
        return str(path.resolve())
    if relative.startswith(".."):
        return str(path.resolve())
    return relative


def build_match_criteria_values(raw_headers: Dict[str, str], body_lines: List[str]) -> Dict[str, str]:
    subject = get_header_case_insensitive(raw_headers, "Subject").strip()
    from_header = get_header_case_insensitive(raw_headers, "From").strip()
    from_contains = extract_email(from_header) if from_header else ""
    body_contains = extract_body_contains(body_lines)
    if not subject:
        raise RuntimeError("template file has no Subject header.")

    return {
        "MAIL_SUBJECT_CONTAINS": subject,
        "MAIL_FROM_CONTAINS": from_contains,
        "MAIL_BODY_CONTAINS": body_contains,
    }


def write_new_full_settings_from_example(target_path: Path, active_profile: str) -> None:
    if not DEFAULT_ENV_EXAMPLE_PATH.exists():
        raise RuntimeError(f"settings example not found: {DEFAULT_ENV_EXAMPLE_PATH}")
    lines = DEFAULT_ENV_EXAMPLE_PATH.read_text(encoding="utf-8").splitlines()

    found = False
    updated: List[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("MAIL_ACTIVE_CONFIG="):
            updated.append(f"MAIL_ACTIVE_CONFIG={format_env_value(active_profile)}")
            found = True
        else:
            updated.append(line)

    if not found:
        if updated and updated[-1] != "":
            updated.append("")
        updated.append("# Optional default match criteria profile")
        updated.append(f"MAIL_ACTIVE_CONFIG={format_env_value(active_profile)}")

    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text("\n".join(updated) + "\n", encoding="utf-8")


def run_template_config_command(args) -> int:
    template_path = resolve_env_path(args.template_file)
    if not template_path.exists():
        print(f"ERROR - template file not found: {args.template_file} (resolved: {template_path})")
        return 3

    raw_headers, body_lines = parse_template_sections(str(template_path))
    try:
        criteria_values = build_match_criteria_values(raw_headers, body_lines)
    except RuntimeError as exc:
        print(f"ERROR - {exc}")
        return 3

    default_name = f"match_criteria_{normalize_template_name(str(template_path))}.env"
    output_value = args.output.strip() if args.output else f"config/{default_name}"
    output_path = resolve_env_path(ensure_env_suffix(output_value))
    if is_protected_settings_path(output_path):
        print(f"ERROR - protected file cannot be overwritten: {DEFAULT_ENV_PATH}")
        return 3

    if output_path.exists() and not args.force:
        print(f"ERROR - output file exists already: {output_path}")
        return 3

    write_match_criteria_env_file(output_path, criteria_values)

    output_ref = path_for_env_reference(output_path)
    print(f"OK - match criteria config created: {output_path}")
    print(f"Template subject -> MAIL_SUBJECT_CONTAINS: {criteria_values['MAIL_SUBJECT_CONTAINS']}")
    if criteria_values["MAIL_FROM_CONTAINS"]:
        print(f"Template from -> MAIL_FROM_CONTAINS: {criteria_values['MAIL_FROM_CONTAINS']}")
    if criteria_values["MAIL_BODY_CONTAINS"]:
        print(f"Template body -> MAIL_BODY_CONTAINS: {criteria_values['MAIL_BODY_CONTAINS']}")

    if args.new_config:
        new_config_candidate = ensure_env_suffix(args.new_config.strip())
        if "/" not in new_config_candidate:
            new_config_candidate = f"config/{new_config_candidate}"
        new_config_path = resolve_env_path(new_config_candidate)
        if is_protected_settings_path(new_config_path):
            print(f"ERROR - protected file cannot be overwritten: {DEFAULT_ENV_PATH}")
            return 3
        if new_config_path.exists():
            print(f"ERROR - new config file exists already: {new_config_path}")
            return 3
        write_new_full_settings_from_example(new_config_path, output_ref)
        print(f"OK - full settings config created from example: {new_config_path}")

    if args.set_default:
        set_default_active_config(DEFAULT_ENV_PATH, output_ref)
        print(f"Default profile set in {DEFAULT_ENV_PATH}: MAIL_ACTIVE_CONFIG={output_ref}")

    return 0
