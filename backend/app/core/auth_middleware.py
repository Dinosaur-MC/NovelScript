"""Auth middleware — extract the current user from a Bearer token.

All functions are synchronous.
"""

from __future__ import annotations

import uuid
from typing import Protocol, runtime_checkable

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.redis import get_redis
from app.core.security import decode_access_token
from app.models.sql import User
from app.services.token_blacklist import is_blacklisted
from app.services.user_cache import get_cached_user, set_cached_user


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
    r=Depends(get_redis),
) -> User:
    """Extract the Bearer token from the request and return the matching User.

    Checks the Redis token blacklist before accepting the JWT, and caches
    user profiles in Redis to reduce database load.

    Raises:
        HTTPException(401): If the token is missing, malformed, expired,
            revoked, or the user no longer exists.
    """
    authorization: str | None = request.headers.get("Authorization")
    if authorization is None:
        raise HTTPException(status_code=401, detail="缺少认证令牌")

    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="无效的认证令牌")

    payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="认证令牌无效或已过期")

    # ── check token blacklist ──────────────────────────────────
    jti = payload.get("jti")
    if jti and is_blacklisted(r, jti):
        raise HTTPException(status_code=401, detail="令牌已被注销")

    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(status_code=401, detail="认证令牌格式错误")

    try:
        uid = uuid.UUID(user_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=401, detail="认证令牌格式错误")

    # ── check user cache ───────────────────────────────────────
    cached = get_cached_user(r, user_id)
    if cached is not None:
        return _cached_dict_to_user(cached)

    # ── database lookup (existing path) ────────────────────────
    user = db.get(User, uid)
    if user is None:
        raise HTTPException(status_code=401, detail="用户不存在")

    # ── populate cache ─────────────────────────────────────────
    set_cached_user(r, user_id, _user_to_cache_dict(user))

    return user


@runtime_checkable
class Owned(Protocol):
    """Protocol for ORM models that carry a nullable ``user_id`` column."""

    user_id: uuid.UUID | None


def require_ownership(
    resource: Owned,
    current_user: User,
    *,
    resource_name: str = "资源",
    action: str = "操作",
) -> None:
    """Raise 403 if *resource* is owned by a different user.

    Resources with ``user_id is None`` (legacy / pre-auth data) are
    treated as unowned and pass the check for all authenticated users.

    Administrators (``role='admin'``) always pass — they can operate on
    any user's resources.
    """
    if current_user.role == "admin":
        return
    if resource.user_id and resource.user_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail=f"无权{action}此{resource_name}",
        )


# ---------------------------------------------------------------------------
# User cache helpers — convert between ORM objects and cacheable dicts
# ---------------------------------------------------------------------------


def _user_to_cache_dict(user: User) -> dict:
    """Serialize a User ORM object to a cacheable dict."""
    return {
        "id": str(user.id),
        "username": user.username,
        "email": user.email,
        "role": user.role,
        "is_active": user.is_active,
        "password_hash": user.password_hash,
    }


def _cached_dict_to_user(data: dict) -> User:
    """Reconstruct a User ORM object from a cached dict."""
    return User(
        id=uuid.UUID(data["id"]),
        username=data["username"],
        email=data["email"],
        role=data["role"],
        is_active=data["is_active"],
        password_hash=data["password_hash"],
    )
