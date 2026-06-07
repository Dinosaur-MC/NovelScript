"""Security utilities — password hashing (argon2) and JWT tokens.

Dependencies: passlib[argon2], pyjwt
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from passlib.context import CryptContext

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Password hashing — argon2 via passlib
# ---------------------------------------------------------------------------

_pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

# JWT secret — in production this MUST come from a secure secrets manager.
# For development we use a hard-coded fallback.
_JWT_SECRET: str = "novelscript-dev-secret-change-in-production"
_JWT_ALGORITHM: str = "HS256"
_JWT_EXPIRE_HOURS: int = 24


def hash_password(password: str) -> str:
    """Hash a plaintext password with argon2."""
    return _pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against its argon2 hash."""
    return _pwd_context.verify(plain_password, hashed_password)


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------

def create_access_token(
    user_id: str,
    expires_delta: timedelta | None = None,
) -> str:
    """Create a signed JWT access token for *user_id*.

    Args:
        user_id: The user's UUID (as a string).
        expires_delta: Custom expiry; defaults to 24 hours.

    Returns:
        Encoded JWT string.
    """
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(hours=_JWT_EXPIRE_HOURS)
    )
    payload = {
        "sub": user_id,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, _JWT_SECRET, algorithm=_JWT_ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    """Decode and validate a JWT access token.

    Returns:
        The token payload as a dict, or ``None`` if the token is
        expired / invalid.
    """
    try:
        payload = jwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        logger.warning("JWT token has expired.")
        return None
    except jwt.InvalidTokenError as exc:
        logger.warning("Invalid JWT token: %s", exc)
        return None


def configure_jwt(
    secret: str,
    algorithm: str = "HS256",
    expire_hours: int = 24,
) -> None:
    """Override JWT defaults (call once at startup)."""
    global _JWT_SECRET, _JWT_ALGORITHM, _JWT_EXPIRE_HOURS
    _JWT_SECRET = secret
    _JWT_ALGORITHM = algorithm
    _JWT_EXPIRE_HOURS = expire_hours
