"""Agent C — Auth endpoint tests (6 tests, all sync).

Uses FastAPI TestClient with dependency override for the test DB session.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.redis import get_redis
from app.main import app


# ---------------------------------------------------------------------------
# Fixture — TestClient wired to the test DB session and fakeredis
# ---------------------------------------------------------------------------


@pytest.fixture
def client(db: Session, redis_client):
    """Return a TestClient wired to the test DB session and fakeredis."""

    def _override_get_db():
        yield db

    def _override_get_redis():
        yield redis_client

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_redis] = _override_get_redis
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Test data helper
# ---------------------------------------------------------------------------


def _register(client: TestClient, username: str, email: str, password: str = "test1234"):
    return client.post(
        "/api/v1/auth/register",
        json={"username": username, "email": email, "password": password},
    )


# ---------------------------------------------------------------------------
# 1. test_register_success
# ---------------------------------------------------------------------------


def test_register_success(client: TestClient):
    """Registering with unique credentials returns 200 and user data."""
    tag = uuid.uuid4().hex[:8]
    resp = _register(client, f"user_{tag}", f"user_{tag}@test.local")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 200
    assert body["data"]["username"] == f"user_{tag}"
    assert "user_id" in body["data"]


# ---------------------------------------------------------------------------
# 2. test_register_duplicate_email_409
# ---------------------------------------------------------------------------


def test_register_duplicate_email_409(client: TestClient):
    """Registering with the same email twice returns 409."""
    tag = uuid.uuid4().hex[:8]
    email = f"dup_{tag}@test.local"
    r1 = _register(client, f"user1_{tag}", email)
    assert r1.status_code == 200

    r2 = _register(client, f"user2_{tag}", email)
    assert r2.status_code == 409


# ---------------------------------------------------------------------------
# 3. test_login_success_returns_token
# ---------------------------------------------------------------------------


def test_login_success_returns_token(client: TestClient):
    """Logging in with correct credentials returns a JWT token."""
    tag = uuid.uuid4().hex[:8]
    email = f"login_{tag}@test.local"
    password = "securepass"
    _register(client, f"loginuser_{tag}", email, password)

    resp = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 200
    assert "token" in body["data"]
    assert body["data"]["user"]["username"] == f"loginuser_{tag}"
    assert body["data"]["user"]["role"] == "user"


# ---------------------------------------------------------------------------
# 4. test_login_wrong_password_401
# ---------------------------------------------------------------------------


def test_login_wrong_password_401(client: TestClient):
    """Logging in with a wrong password returns 401."""
    tag = uuid.uuid4().hex[:8]
    email = f"wrong_{tag}@test.local"
    _register(client, f"wronguser_{tag}", email, "correct")

    resp = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "wrongpass"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 5. test_me_with_valid_token
# ---------------------------------------------------------------------------


def test_me_with_valid_token(client: TestClient):
    """GET /me with a valid Bearer token returns the user profile."""
    tag = uuid.uuid4().hex[:8]
    email = f"me_{tag}@test.local"
    password = "mepassword"
    _register(client, f"meuser_{tag}", email, password)

    login_resp = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    token = login_resp.json()["data"]["token"]

    resp = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 200
    assert body["data"]["username"] == f"meuser_{tag}"
    assert body["data"]["email"] == email
    assert body["data"]["role"] == "user"
    assert "id" in body["data"]


# ---------------------------------------------------------------------------
# 6. test_me_without_token_401
# ---------------------------------------------------------------------------


def test_me_without_token_401(client: TestClient):
    """GET /me without any Authorization header returns 401."""
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 401
