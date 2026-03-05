import secrets
from datetime import datetime, timezone
from typing import Optional

import jwt
from jwt.exceptions import DecodeError, ExpiredSignatureError, InvalidAlgorithmError, InvalidSignatureError


JWT_ISSUER = "mail-check"
JWT_SUBJECT = "mail-delivery-check"
MIN_JWT_SECRET_LENGTH = 32


def validate_mailcheck_secret(secret: str) -> None:
    if len(secret) < MIN_JWT_SECRET_LENGTH:
        raise RuntimeError(
            f"MAIL_CHECK_JWT_SECRET must be at least {MIN_JWT_SECRET_LENGTH} characters long."
        )


def create_mailcheck_jwt(secret: str, issued_at: datetime) -> str:
    """Create a signed HS256 JWT used to correlate send and receive checks."""
    validate_mailcheck_secret(secret)
    iat = int(issued_at.timestamp())
    payload = {
        "iss": JWT_ISSUER,
        "sub": JWT_SUBJECT,
        "iat": iat,
        "jti": secrets.token_hex(12),
    }
    token = jwt.encode(payload, secret, algorithm="HS256", headers={"typ": "JWT"})
    return token if isinstance(token, str) else token.decode("utf-8")


def verify_mailcheck_jwt(token: str, secret: str, max_age_seconds: int) -> datetime:
    """Verify signature and age of a mail-check JWT and return its issue time."""
    validate_mailcheck_secret(secret)
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            options={
                "require": ["iat", "iss", "sub"],
                "verify_exp": False,
            },
            issuer=JWT_ISSUER,
        )
    except ExpiredSignatureError as exc:
        raise RuntimeError("JWT expired.") from exc
    except InvalidSignatureError as exc:
        raise RuntimeError("JWT signature invalid.") from exc
    except InvalidAlgorithmError as exc:
        raise RuntimeError("JWT algorithm not supported.") from exc
    except DecodeError as exc:
        raise RuntimeError("JWT payload invalid.") from exc
    except jwt.InvalidTokenError as exc:
        raise RuntimeError(f"JWT invalid: {exc}") from exc

    if payload.get("sub") != JWT_SUBJECT:
        raise RuntimeError("JWT subject invalid.")

    iat = payload.get("iat")
    if not isinstance(iat, int):
        raise RuntimeError("JWT iat claim missing.")

    try:
        issued_at = datetime.fromtimestamp(iat, tz=timezone.utc)
    except Exception as exc:
        raise RuntimeError("JWT iat claim invalid.") from exc
    now_utc = datetime.now(timezone.utc)
    max_age = max(1, max_age_seconds)
    age = (now_utc - issued_at).total_seconds()
    if age < 0:
        raise RuntimeError("JWT iat is in the future.")
    if age > max_age:
        raise RuntimeError("JWT expired.")

    return issued_at


def parse_mailcheck_timestamp(value: str) -> Optional[datetime]:
    """Parse ISO-like timestamps from headers/body and normalize to UTC."""
    cleaned = value.strip()
    if not cleaned:
        return None
    try:
        if cleaned.endswith("Z"):
            cleaned = cleaned[:-1] + "+00:00"
        parsed = datetime.fromisoformat(cleaned)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
