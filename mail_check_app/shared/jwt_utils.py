import base64
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timezone
from typing import Optional


def b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def b64url_decode(value: str) -> bytes:
    padding = "=" * ((4 - len(value) % 4) % 4)
    return base64.urlsafe_b64decode(value + padding)


def create_mailcheck_jwt(secret: str, issued_at: datetime) -> str:
    """Create a signed HS256 JWT used to correlate send and receive checks."""
    header = {"alg": "HS256", "typ": "JWT"}
    iat = int(issued_at.timestamp())
    payload = {
        "iss": "mail-check",
        "sub": "mail-delivery-check",
        "iat": iat,
        "jti": secrets.token_hex(12),
    }
    header_b64 = b64url_encode(json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    payload_b64 = b64url_encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    signature = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    signature_b64 = b64url_encode(signature)
    return f"{header_b64}.{payload_b64}.{signature_b64}"


def verify_mailcheck_jwt(token: str, secret: str, max_age_seconds: int) -> datetime:
    """Verify signature and age of a mail-check JWT and return its issue time."""
    parts = token.split(".")
    if len(parts) != 3:
        raise RuntimeError("JWT format invalid.")

    header_b64, payload_b64, signature_b64 = parts
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    expected_signature = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    try:
        provided_signature = b64url_decode(signature_b64)
    except Exception as exc:
        raise RuntimeError("JWT signature encoding invalid.") from exc
    if not hmac.compare_digest(expected_signature, provided_signature):
        raise RuntimeError("JWT signature invalid.")

    try:
        header = json.loads(b64url_decode(header_b64).decode("utf-8"))
        payload = json.loads(b64url_decode(payload_b64).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError("JWT payload invalid.") from exc

    if header.get("alg") != "HS256":
        raise RuntimeError("JWT algorithm not supported.")

    iat = payload.get("iat")
    if not isinstance(iat, int):
        raise RuntimeError("JWT iat claim missing.")

    issued_at = datetime.fromtimestamp(iat, tz=timezone.utc)
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
