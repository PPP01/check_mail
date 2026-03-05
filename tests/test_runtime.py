from pathlib import Path

import pytest

from mail_check_app.runtime import ensure_active_profile_required, load_runtime_env, resolve_env_path


def test_resolve_env_path_resolves_relative_to_project_root() -> None:
    resolved = resolve_env_path("config/settings.env.example")

    assert resolved.name == "settings.env.example"
    assert resolved.is_absolute()


def test_load_runtime_env_raises_for_missing_override_file() -> None:
    with pytest.raises(RuntimeError, match="Configured env file not found"):
        load_runtime_env(config_override="config/does_not_exist.env", require_active_profile=False)


def test_load_runtime_env_returns_warning_for_missing_active_profile_when_optional(monkeypatch) -> None:
    monkeypatch.setenv("MAIL_ACTIVE_CONFIG", "config/does_not_exist.env")

    warning = load_runtime_env(require_active_profile=False)

    assert "Configured active profile not found" in warning


def test_ensure_active_profile_required_returns_error_without_active_profile(monkeypatch) -> None:
    monkeypatch.delenv("MAIL_ACTIVE_CONFIG", raising=False)

    rc = ensure_active_profile_required("check")

    assert rc == 3


def test_ensure_active_profile_required_allows_send_without_profile(monkeypatch) -> None:
    monkeypatch.delenv("MAIL_ACTIVE_CONFIG", raising=False)

    rc = ensure_active_profile_required("send")

    assert rc == 0
