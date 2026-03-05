import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENV_PATH = PROJECT_ROOT / "config" / "settings.env"
DEFAULT_ENV_EXAMPLE_PATH = PROJECT_ROOT / "config" / "settings.env.example"


def resolve_env_path(value: str) -> Path:
    raw_path = Path(value)
    if raw_path.is_absolute():
        return raw_path
    return (PROJECT_ROOT / raw_path).resolve()


def env_bool(primary_key: str, fallback_key: str, default: str = "0") -> bool:
    value = os.getenv(primary_key)
    if value is None:
        value = os.getenv(fallback_key, default)
    return value == "1"


def read_env_key(path: Path, key: str) -> str:
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
        selected_path = resolve_env_path(selected_config)
        if not selected_path.exists():
            raise RuntimeError(
                f"Configured env file not found: {selected_config} (resolved: {selected_path})"
            )
        selected_active_profile = read_env_key(selected_path, "MAIL_ACTIVE_CONFIG")
        if not selected_active_profile and require_active_profile:
            raise RuntimeError(
                f"Configured env file must define non-empty MAIL_ACTIVE_CONFIG: {selected_path}"
            )
        load_dotenv(dotenv_path=selected_path, override=True)

    active_profile = os.getenv("MAIL_ACTIVE_CONFIG", "").strip()
    if not active_profile:
        return ""

    profile_path = resolve_env_path(active_profile)
    if not profile_path.exists():
        message = f"Configured active profile not found: {active_profile} (resolved: {profile_path})"
        if require_active_profile:
            raise RuntimeError(message)
        return message
    load_dotenv(dotenv_path=profile_path, override=True)
    return ""


def ensure_active_profile_required(command: str) -> int:
    if command in {"template-config", "send"}:
        return 0
    active_profile = os.getenv("MAIL_ACTIVE_CONFIG", "").strip()
    if active_profile:
        return 0
    print("ERROR - MAIL_ACTIVE_CONFIG is required in settings config or via --config.")
    return 3
