"""Auth router — register, login, logout, current user.

All endpoints are synchronous (no async/await).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth_middleware import get_current_user
from app.core.db import get_db
from app.core.security import (
    create_access_token,
    hash_password,
    verify_password,
)
from app.models.http import BaseResponse
from app.models.sql import User
from app.services.base import BaseCRUD

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Auth"])

_user_crud = BaseCRUD[User](User)


# ---------------------------------------------------------------------------
# Pydantic request models
# ---------------------------------------------------------------------------

class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=150)
    email: str = Field(..., min_length=5, max_length=320)
    password: str = Field(..., min_length=6, max_length=128)


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=320)
    password: str = Field(..., min_length=1, max_length=128)


# ---------------------------------------------------------------------------
# POST /register
# ---------------------------------------------------------------------------

@router.post("/register")
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    """Register a new user account."""
    # Check duplicate email
    existing = db.execute(
        select(User).where(User.email == body.email)
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="邮箱已被注册")

    # Check duplicate username
    existing = db.execute(
        select(User).where(User.username == body.username)
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="用户名已被占用")

    # Create user
    user = User(
        username=body.username,
        email=body.email,
        password_hash=hash_password(body.password),
    )
    created = _user_crud.create(db, user)

    return BaseResponse(
        code=200,
        message="注册成功",
        data={"user_id": str(created.id), "username": created.username},
    )


# ---------------------------------------------------------------------------
# POST /login
# ---------------------------------------------------------------------------

@router.post("/login")
def login(body: LoginRequest, db: Session = Depends(get_db)):
    """Authenticate user and return a JWT access token."""
    user = db.execute(
        select(User).where(User.email == body.email)
    ).scalar_one_or_none()

    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="邮箱或密码错误")

    # Update last login
    user.last_login_at = datetime.now(timezone.utc)
    db.add(user)
    db.flush()

    token = create_access_token(str(user.id))

    return BaseResponse(
        code=200,
        message="登录成功",
        data={
            "token": token,
            "user": {
                "id": str(user.id),
                "username": user.username,
                "role": user.role,
            },
        },
    )


# ---------------------------------------------------------------------------
# POST /logout
# ---------------------------------------------------------------------------

@router.post("/logout")
def logout():
    """Stub logout endpoint."""
    return BaseResponse(code=200, message="已登出")


# ---------------------------------------------------------------------------
# GET /me
# ---------------------------------------------------------------------------

@router.get("/me")
def me(current_user: User = Depends(get_current_user)):
    """Return the current authenticated user's profile."""
    return BaseResponse(
        code=200,
        message="请求成功",
        data={
            "id": str(current_user.id),
            "username": current_user.username,
            "email": current_user.email,
            "role": current_user.role,
        },
    )
