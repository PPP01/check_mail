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
            f"MAIL_CHECK_JWT_SECRET muss mindestens {MIN_JWT_SECRET_LENGTH} Zeichen lang sein."
        )


def create_mailcheck_jwt(secret: str, issued_at: datetime, max_age_seconds: int) -> str:
    """Erstellt ein signiertes HS256-JWT zur Korrelation von Sende- und Empfangsprüfungen."""
    validate_mailcheck_secret(secret)
    iat = int(issued_at.timestamp())
    exp = iat + max(1, max_age_seconds)
    payload = {
        "iss": JWT_ISSUER,
        "sub": JWT_SUBJECT,
        "iat": iat,
        "exp": exp,
        "jti": secrets.token_hex(12),
    }
    token = jwt.encode(payload, secret, algorithm="HS256", headers={"typ": "JWT"})
    return token if isinstance(token, str) else token.decode("utf-8")


def verify_mailcheck_jwt(token: str, secret: str) -> datetime:
    """Verifiziert Signatur und Ablauf eines JWTs und gibt den Erstellungszeitpunkt zurück."""
    validate_mailcheck_secret(secret)
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            options={
                "require": ["iat", "iss", "sub", "exp"],
                "verify_exp": True,
            },
            issuer=JWT_ISSUER,
        )
    except ExpiredSignatureError as exc:
        raise RuntimeError("JWT ist abgelaufen.") from exc
    except InvalidSignatureError as exc:
        raise RuntimeError("JWT-Signatur ist ungültig.") from exc
    except InvalidAlgorithmError as exc:
        raise RuntimeError("JWT-Algorithmus wird nicht unterstützt.") from exc
    except DecodeError as exc:
        raise RuntimeError("JWT-Payload ist ungültig.") from exc
    except jwt.InvalidTokenError as exc:
        raise RuntimeError(f"JWT ist ungültig: {exc}") from exc

    if payload.get("sub") != JWT_SUBJECT:
        raise RuntimeError("JWT-Betreff ist ungültig.")

    iat = payload.get("iat")
    if not isinstance(iat, int):
        raise RuntimeError("JWT-iat-Claim fehlt.")

    try:
        return datetime.fromtimestamp(iat, tz=timezone.utc)
    except Exception as exc:
        raise RuntimeError("JWT-iat-Claim ist ungültig.") from exc


def parse_mailcheck_timestamp(value: str) -> Optional[datetime]:
    """Parst ISO-ähnliche Zeitstempel aus Headern/Body und normalisiert auf UTC."""
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
