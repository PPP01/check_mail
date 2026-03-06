import json
import shlex
import sys
from typing import List, Tuple

import httpx


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


def build_icinga_payload(args, exit_status: int, output: str) -> dict:
    """Erstellt den JSON-Payload für die Icinga process-check-result API."""
    plugin_output, performance_data = split_plugin_output_and_perfdata(output)
    payload = {
        "type": "Service",
        "filter": f'host.name=="{args.icinga_host}" && service.name=="{args.icinga_service}"',
        "exit_status": exit_status,
        "plugin_output": plugin_output,
    }
    if performance_data:
        payload["performance_data"] = performance_data
    return payload


def _allow_debug_password_output(args) -> bool:
    return bool(getattr(args, "debug_icinga_show_password", False)) and sys.stdout.isatty()


def build_curl_command(endpoint: str, args, payload: dict, include_password: bool = False) -> str:
    payload_json = json.dumps(payload, ensure_ascii=False)
    insecure = "--insecure " if not args.icinga_verify_tls else ""
    shown_password = args.icinga_password if include_password else "*****"
    return (
        f"curl -sS -X POST {insecure}"
        f"-u {shlex.quote(f'{args.icinga_user}:{shown_password}')} "
        f"-H 'Accept: application/json' "
        f"-H 'Content-Type: application/json' "
        f"{shlex.quote(endpoint)} "
        f"-d {shlex.quote(payload_json)}"
    )


def submit_passive_result(args, exit_status: int, output: str) -> str:
    """Übermittelt ein passives Ergebnis an Icinga und gibt den API-Status-Text zurück."""
    endpoint = args.icinga_url.rstrip("/") + "/v1/actions/process-check-result"
    payload = build_icinga_payload(args, exit_status, output)

    if args.debug_icinga:
        split_output, split_perfdata = split_plugin_output_and_perfdata(output)
        print("Icinga endpoint:", endpoint)
        print("Icinga plugin_output:", split_output)
        print("Icinga performance_data:", split_perfdata if split_perfdata else "[]")
        print("Icinga payload:", json.dumps(payload, ensure_ascii=False))
        print(
            "Icinga curl:",
            build_curl_command(endpoint, args, payload, include_password=_allow_debug_password_output(args)),
        )
        if args.icinga_dry_run:
            return "dry-run: submit skipped"

    try:
        with httpx.Client(verify=args.icinga_verify_tls, timeout=15.0) as client:
            resp = client.post(
                endpoint,
                json=payload,
                auth=(args.icinga_user, args.icinga_password),
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(f"Icinga-API gab Status {exc.response.status_code} zurück: {exc.response.text}") from exc
    except (httpx.RequestError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Fehler bei der Übermittlung an die Icinga-API: {exc}") from exc

    results = data.get("results", [])
    if not results:
        raise RuntimeError(
            "Icinga-API gab keine Ergebnisse zurück. Prüfe ICINGA_HOST/ICINGA_SERVICE und API-Berechtigungen."
        )

    bad_results = [r for r in results if normalize_api_code(r.get("code")) >= 300]
    if bad_results:
        statuses = "; ".join(str(r.get("status", "unbekannter Fehler")) for r in bad_results)
        raise RuntimeError(f"Icinga-API hat das Prüfergebnis abgelehnt: {statuses}")

    return "; ".join(str(r.get("status", "ok")) for r in results)


def missing_icinga_args(args) -> List[str]:
    """Gibt fehlende obligatorische Icinga-Argumente für eine aussagekräftige Fehlermeldung zurück."""
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
