"""Auth primitives — spec §8.

JWT bearer with a short-lived access token and a long-lived refresh token.

Password hashing uses argon2id via ``argon2-cffi``. An earlier version used
PBKDF2-HMAC-SHA256 from the standard library because bcrypt/argon2 usually
need a compiler this dev machine doesn't have — but argon2-cffi ships a
prebuilt wheel for this platform (cp39-abi3-win_amd64), so that tradeoff
turned out not to apply here. See spec-deviations.md §10.
"""
import hashlib
import hmac
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from .config import get_settings
from .errors import unauthorized

settings = get_settings()

# Defaults (19 MiB memory, 2 iterations, 1 lane) follow OWASP's argon2id
# baseline for an interactive login path — deliberately not tuned up, since
# this runs synchronously in the request path and a heavier cost multiplies
# straight into login latency.
_hasher = PasswordHasher()


# --- Passwords -------------------------------------------------------------
def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, stored: str) -> bool:
    try:
        return _hasher.verify(stored, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


# --- Tokens ----------------------------------------------------------------
def _encode(payload: Dict[str, Any]) -> str:
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(user_id: uuid.UUID) -> str:
    now = datetime.now(timezone.utc)
    return _encode(
        {
            "sub": str(user_id),
            "typ": "access",
            "iat": int(now.timestamp()),
            "exp": int(
                (
                    now + timedelta(minutes=settings.access_token_ttl_minutes)
                ).timestamp()
            ),
            "jti": secrets.token_urlsafe(8),
        }
    )


def create_refresh_token(user_id: uuid.UUID) -> str:
    now = datetime.now(timezone.utc)
    return _encode(
        {
            "sub": str(user_id),
            "typ": "refresh",
            "iat": int(now.timestamp()),
            "exp": int(
                (now + timedelta(days=settings.refresh_token_ttl_days)).timestamp()
            ),
            "jti": secrets.token_urlsafe(8),
        }
    )


def create_token_pair(user_id: uuid.UUID) -> Tuple[str, str, int]:
    return (
        create_access_token(user_id),
        create_refresh_token(user_id),
        settings.access_token_ttl_minutes * 60,
    )


def decode_token(token: str, expected_type: str) -> uuid.UUID:
    """Return the subject, or raise the §6 ``unauthorized`` envelope."""
    try:
        payload = jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
    except jwt.ExpiredSignatureError:
        raise unauthorized("Token has expired")
    except jwt.PyJWTError:
        raise unauthorized()

    if payload.get("typ") != expected_type:
        raise unauthorized("Wrong token type")
    try:
        return uuid.UUID(str(payload.get("sub")))
    except (ValueError, TypeError):
        raise unauthorized()


# --- Signed media URLs (local storage backend only) ------------------------
def sign_media_key(key: str, ttl_seconds: Optional[int] = None) -> str:
    """HMAC a storage key so the dev media route is not an open file server."""
    ttl = ttl_seconds if ttl_seconds is not None else settings.signed_url_ttl_seconds
    expires = int(time.time()) + ttl
    message = "{0}:{1}".format(key, expires).encode("utf-8")
    signature = hmac.new(
        settings.jwt_secret.encode("utf-8"), message, hashlib.sha256
    ).hexdigest()[:32]
    return "{0}.{1}".format(expires, signature)


def verify_media_signature(key: str, token: str) -> bool:
    try:
        expires_raw, signature = token.split(".", 1)
        expires = int(expires_raw)
    except (ValueError, AttributeError):
        return False
    if expires < int(time.time()):
        return False
    message = "{0}:{1}".format(key, expires).encode("utf-8")
    expected = hmac.new(
        settings.jwt_secret.encode("utf-8"), message, hashlib.sha256
    ).hexdigest()[:32]
    return hmac.compare_digest(expected, signature)
