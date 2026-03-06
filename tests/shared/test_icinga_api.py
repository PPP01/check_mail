import json
from types import SimpleNamespace

import httpx
import pytest

from mail_check_app.shared.icinga_api import (
    _allow_debug_password_output,
    build_icinga_payload,
    missing_icinga_args,
    submit_passive_result,
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
        debug_icinga_show_password=False,
        icinga_dry_run=False,
    )


def test_split_plugin_output_and_perfdata_parses_perfdata() -> None:
    output = "OK - all good | metric_a=1s;;;; metric_b=2;;;;"

    plugin_output, perfdata = split_plugin_output_and_perfdata(output)

    assert plugin_output == "OK - all good"
    assert perfdata == ["metric_a=1s;;;;", "metric_b=2;;;;"]


def test_build_icinga_payload_builds_expected_structure() -> None:
    args = _args()

    payload = build_icinga_payload(
        args=args,
        exit_status=2,
        output="CRITICAL - failed | foo=1;;;;",
    )

    assert payload["type"] == "Service"
    assert payload["exit_status"] == 2
    assert payload["plugin_output"] == "CRITICAL - failed"
    assert payload["performance_data"] == ["foo=1;;;;"]


def test_missing_icinga_args_returns_expected_keys() -> None:
    args = _args()
    args.icinga_user = ""
    args.icinga_service = ""

    missing = missing_icinga_args(args)

    assert "ICINGA_USER/--icinga-user" in missing
    assert "ICINGA_SERVICE/--icinga-service" in missing


def test_allow_debug_password_output_requires_flag_and_tty(monkeypatch) -> None:
    class FakeStdout:
        def __init__(self, is_tty: bool) -> None:
            self._is_tty = is_tty

        def isatty(self) -> bool:
            return self._is_tty

    args = _args()
    monkeypatch.setattr("mail_check_app.shared.icinga_api.sys.stdout", FakeStdout(True))
    assert _allow_debug_password_output(args) is False

    args.debug_icinga_show_password = True
    assert _allow_debug_password_output(args) is True

    monkeypatch.setattr("mail_check_app.shared.icinga_api.sys.stdout", FakeStdout(False))
    assert _allow_debug_password_output(args) is False


def test_submit_passive_result_masks_password_in_debug_curl(monkeypatch, capsys) -> None:
    args = _args()
    args.debug_icinga = True
    args.icinga_dry_run = True

    monkeypatch.setattr("mail_check_app.shared.icinga_api._allow_debug_password_output", lambda _args: False)

    result = submit_passive_result(args, 0, "OK - test")

    captured = capsys.readouterr().out
    assert result == "dry-run: submit skipped"
    assert "api:*****" in captured
    assert "api:pw" not in captured


def test_submit_passive_result_shows_password_only_if_explicitly_allowed(monkeypatch, capsys) -> None:
    args = _args()
    args.debug_icinga = True
    args.icinga_dry_run = True

    monkeypatch.setattr("mail_check_app.shared.icinga_api._allow_debug_password_output", lambda _args: True)

    result = submit_passive_result(args, 0, "OK - test")

    captured = capsys.readouterr().out
    assert result == "dry-run: submit skipped"
    assert "api:pw" in captured


def test_submit_passive_result_success(monkeypatch) -> None:
    args = _args()
    
    class FakeResponse:
        def __init__(self):
            self.status_code = 200
            self.text = '{"results": [{"code": 200, "status": "Filter matched 1 service(s)"}]}'
        def raise_for_status(self):
            pass
        def json(self):
            return json.loads(self.text)

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(httpx, "Client", FakeClient)

    status = submit_passive_result(args, 0, "OK - test")
    assert "Filter matched 1 service(s)" in status


def test_submit_passive_result_handles_api_error(monkeypatch) -> None:
    args = _args()
    
    class FakeResponse:
        def __init__(self):
            self.status_code = 404
            self.text = "Not Found"
        def raise_for_status(self):
            raise httpx.HTTPStatusError("404", request=None, response=self)

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(httpx, "Client", FakeClient)

    with pytest.raises(RuntimeError, match="Icinga-API gab Status 404 zurück"):
        submit_passive_result(args, 2, "CRITICAL - test")
