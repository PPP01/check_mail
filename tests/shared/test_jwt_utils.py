from datetime import datetime, timedelta, timezone

import pytest

from mail_check_app.shared.jwt_utils import create_mailcheck_jwt, parse_mailcheck_timestamp, verify_mailcheck_jwt


def test_create_and_verify_jwt_roundtrip() -> None:
    issued_at = datetime.now(timezone.utc) - timedelta(seconds=2)
    token = create_mailcheck_jwt("secret", issued_at)

    verified_issued_at = verify_mailcheck_jwt(token, "secret", max_age_seconds=60)

    assert int(verified_issued_at.timestamp()) == int(issued_at.timestamp())


def test_verify_jwt_rejects_invalid_signature() -> None:
    issued_at = datetime.now(timezone.utc)
    token = create_mailcheck_jwt("secret-a", issued_at)

    with pytest.raises(RuntimeError, match="JWT signature invalid"):
        verify_mailcheck_jwt(token, "secret-b", max_age_seconds=60)


def test_verify_jwt_rejects_expired_token() -> None:
    issued_at = datetime.now(timezone.utc) - timedelta(seconds=5)
    token = create_mailcheck_jwt("secret", issued_at)

    with pytest.raises(RuntimeError, match="JWT expired"):
        verify_mailcheck_jwt(token, "secret", max_age_seconds=1)


def test_parse_mailcheck_timestamp_supports_z_suffix() -> None:
    parsed = parse_mailcheck_timestamp("2026-01-01T12:00:00Z")

    assert parsed is not None
    assert parsed.tzinfo is not None
    assert parsed.utcoffset().total_seconds() == 0
