from types import SimpleNamespace

from mail_check_app.shared.icinga_api import (
    build_icinga_submit,
    missing_icinga_args,
    split_plugin_output_and_perfdata,
)


def _args() -> SimpleNamespace:
    return SimpleNamespace(
        icinga_url="https://icinga.example.net:5665",
        icinga_user="api",
        icinga_password="pw",
        icinga_host="host-a",
        icinga_service="svc-a",
        icinga_verify_tls=True,
        debug_icinga=False,
        icinga_dry_run=False,
    )


def test_split_plugin_output_and_perfdata_parses_perfdata() -> None:
    output = "OK - all good | metric_a=1s;;;; metric_b=2;;;;"

    plugin_output, perfdata = split_plugin_output_and_perfdata(output)

    assert plugin_output == "OK - all good"
    assert perfdata == ["metric_a=1s;;;;", "metric_b=2;;;;"]


def test_build_icinga_submit_builds_payload_and_auth_header() -> None:
    args = _args()

    payload, headers = build_icinga_submit(
        endpoint="https://unused",
        args=args,
        exit_status=2,
        output="CRITICAL - failed | foo=1;;;;",
    )

    assert payload["type"] == "Service"
    assert payload["exit_status"] == 2
    assert payload["plugin_output"] == "CRITICAL - failed"
    assert payload["performance_data"] == ["foo=1;;;;"]
    assert "Authorization" in headers
    assert headers["Authorization"].startswith("Basic ")


def test_missing_icinga_args_returns_expected_keys() -> None:
    args = _args()
    args.icinga_user = ""
    args.icinga_service = ""

    missing = missing_icinga_args(args)

    assert "ICINGA_USER/--icinga-user" in missing
    assert "ICINGA_SERVICE/--icinga-service" in missing
