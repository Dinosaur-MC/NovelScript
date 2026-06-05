"""Security utilities: password hashing and JWT encode / decode."""

from __future__ import annotations

import time

import pytest

from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


# ---------------------------------------------------------------------------
# 1. hash + verify
# ---------------------------------------------------------------------------

def test_hash_and_verify_password():
    """A hashed password can be verified against its plaintext."""
    plain = "s3cur3-p@ss"
    hashed = hash_password(plain)

    assert hashed != plain
    assert hashed.startswith("$argon2")
    assert verify_password(plain, hashed) is True
    assert verify_password("wrong", hashed) is False


# ---------------------------------------------------------------------------
# 2. JWT create + decode
# ---------------------------------------------------------------------------

def test_jwt_create_and_decode():
    """A freshly created JWT decodes back with the correct subject."""
    token = create_access_token("user-123")
    payload = decode_access_token(token)
    assert payload is not None
    assert payload["sub"] == "user-123"
    assert "exp" in payload
    assert "iat" in payload


# ---------------------------------------------------------------------------
# 3. expired token
# ---------------------------------------------------------------------------

def test_expired_token_returns_none():
    """A token with a negative expiry returns None on decode."""
    from datetime import timedelta

    token = create_access_token("user-456", expires_delta=timedelta(seconds=-1))
    payload = decode_access_token(token)
    assert payload is None
