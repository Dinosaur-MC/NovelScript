"""Auth middleware — extract the current user from a Bearer token.

All functions are synchronous.
"""

from __future__ import annotations

import uuid
from typing import Protocol, runtime_checkable

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import decode_access_token
from app.models.sql import User


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """Extract the Bearer token from the request and return the matching User.

    Raises:
        HTTPException(401): If the token is missing, malformed, expired,
            or the user no longer exists.
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

    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(status_code=401, detail="认证令牌格式错误")

    try:
        uid = uuid.UUID(user_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=401, detail="认证令牌格式错误")

    user = db.get(User, uid)
    if user is None:
        raise HTTPException(status_code=401, detail="用户不存在")

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
    """
    if resource.user_id and resource.user_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail=f"无权{action}此{resource_name}",
        )
