import base64
import json
import shlex
import ssl
import urllib.error
import urllib.request
from typing import List, Tuple


def normalize_api_code(value: object) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def split_plugin_output_and_perfdata(output: str) -> Tuple[str, List[str]]:
    if "|" not in output:
        return output.strip(), []
    plugin_output, perfdata_raw = output.split("|", 1)
    perf_items = [item.strip() for item in perfdata_raw.strip().split() if item.strip()]
    return plugin_output.strip(), perf_items


def build_icinga_submit(endpoint: str, args, exit_status: int, output: str) -> Tuple[dict, dict]:
    """Build JSON payload and HTTP headers for Icinga process-check-result API."""
    plugin_output, performance_data = split_plugin_output_and_perfdata(output)
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
        + base64.b64encode(f"{args.icinga_user}:{args.icinga_password}".encode("utf-8")).decode("ascii"),
    }
    return payload, headers


def build_curl_command(endpoint: str, args, payload: dict) -> str:
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


def submit_passive_result(args, exit_status: int, output: str) -> str:
    """Submit a passive result to Icinga and return API status text."""
    endpoint = args.icinga_url.rstrip("/") + "/v1/actions/process-check-result"
    payload, headers = build_icinga_submit(endpoint, args, exit_status, output)

    if args.debug_icinga:
        split_output, split_perfdata = split_plugin_output_and_perfdata(output)
        print("Icinga endpoint:", endpoint)
        print("Icinga plugin_output:", split_output)
        print("Icinga performance_data:", split_perfdata if split_perfdata else "[]")
        print("Icinga payload:", json.dumps(payload, ensure_ascii=False))
        print("Icinga curl:", build_curl_command(endpoint, args, payload))
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

    bad_results = [r for r in results if normalize_api_code(r.get("code")) >= 300]
    if bad_results:
        statuses = "; ".join(str(r.get("status", "unknown error")) for r in bad_results)
        raise RuntimeError(f"Icinga API rejected check result: {statuses}")

    return "; ".join(str(r.get("status", "ok")) for r in results)


def missing_icinga_args(args) -> List[str]:
    """Return missing mandatory Icinga argument names for actionable error output."""
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
