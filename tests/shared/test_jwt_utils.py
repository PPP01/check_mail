from datetime import datetime, timedelta, timezone

import pytest
import jwt

from mail_check_app.shared.jwt_utils import (
    JWT_ISSUER,
    JWT_SUBJECT,
    MIN_JWT_SECRET_LENGTH,
    create_mailcheck_jwt,
    parse_mailcheck_timestamp,
    verify_mailcheck_jwt,
)


SECRET = "x" * MIN_JWT_SECRET_LENGTH


def test_create_and_verify_jwt_roundtrip() -> None:
    issued_at = datetime.now(timezone.utc) - timedelta(seconds=2)
    token = create_mailcheck_jwt(SECRET, issued_at, max_age_seconds=60)

    verified_issued_at = verify_mailcheck_jwt(token, SECRET)

    assert int(verified_issued_at.timestamp()) == int(issued_at.timestamp())


def test_verify_jwt_rejects_invalid_signature() -> None:
    issued_at = datetime.now(timezone.utc)
    token = create_mailcheck_jwt("a" * MIN_JWT_SECRET_LENGTH, issued_at, max_age_seconds=60)

    with pytest.raises(RuntimeError, match="JWT-Signatur ist ungültig"):
        verify_mailcheck_jwt(token, "b" * MIN_JWT_SECRET_LENGTH)


def test_verify_jwt_rejects_expired_token() -> None:
    issued_at = datetime.now(timezone.utc) - timedelta(seconds=5)
    # Token erstellen, das bereits abgelaufen ist
    token = create_mailcheck_jwt(SECRET, issued_at, max_age_seconds=2)

    with pytest.raises(RuntimeError, match="JWT ist abgelaufen"):
        verify_mailcheck_jwt(token, SECRET)


def test_verify_jwt_rejects_invalid_subject() -> None:
    issued_at = datetime.now(timezone.utc)
    payload = {
        "iss": JWT_ISSUER,
        "sub": "other-subject",
        "iat": int(issued_at.timestamp()),
        "exp": int(issued_at.timestamp()) + 60,
    }
    token = jwt.encode(payload, SECRET, algorithm="HS256", headers={"typ": "JWT"})

    with pytest.raises(RuntimeError, match="JWT-Betreff ist ungültig"):
        verify_mailcheck_jwt(token, SECRET)


def test_verify_jwt_rejects_invalid_issuer() -> None:
    issued_at = datetime.now(timezone.utc)
    payload = {
        "iss": "other-issuer",
        "sub": JWT_SUBJECT,
        "iat": int(issued_at.timestamp()),
        "exp": int(issued_at.timestamp()) + 60,
    }
    token = jwt.encode(payload, SECRET, algorithm="HS256", headers={"typ": "JWT"})

    with pytest.raises(RuntimeError, match="JWT ist ungültig"):
        verify_mailcheck_jwt(token, SECRET)


def test_verify_jwt_rejects_short_secret() -> None:
    issued_at = datetime.now(timezone.utc)
    token = create_mailcheck_jwt(SECRET, issued_at, max_age_seconds=60)

    with pytest.raises(RuntimeError, match="mindestens"):
        verify_mailcheck_jwt(token, "short")


def test_parse_mailcheck_timestamp_supports_z_suffix() -> None:
    parsed = parse_mailcheck_timestamp("2026-01-01T12:00:00Z")

    assert parsed is not None
    assert parsed.tzinfo is not None
    assert parsed.utcoffset().total_seconds() == 0
