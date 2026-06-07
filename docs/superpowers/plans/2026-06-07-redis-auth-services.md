# Redis-Backed Auth & API Services — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add real JWT logout (token blacklisting), login rate limiting, and user-profile caching to the FastAPI backend, all backed by the existing Redis instance.

**Architecture:** New `core/redis.py` provides a sync Redis connection pool + FastAPI dependency. Three new service modules (`token_blacklist.py`, `rate_limiter.py`, `user_cache.py`) use it. `auth_middleware.py` integrates blacklist + cache checks before DB queries. `api/v1/auth.py` gains a real logout endpoint and login rate limiting. Tests use `fakeredis` to avoid real Redis.

**Tech Stack:** Python 3.13, redis-py (sync), fakeredis (test), FastAPI Depends, JWT with `jti` claim.

**Total files:** 4 new, 6 modified, 3 new test files, 5 modified test files.

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| **Create** | `backend/app/core/redis.py` | Redis connection pool + `get_redis()` DI + `get_redis_client()` helper |
| **Modify** | `backend/pyproject.toml` | Add `fakeredis` dev dependency |
| **Modify** | `backend/app/core/security.py` | Add `jti` claim to `create_access_token()` |
| **Create** | `backend/app/services/token_blacklist.py` | `blacklist_token()` / `is_blacklisted()` — SET with TTL |
| **Create** | `backend/app/services/rate_limiter.py` | `check_rate_limit()` / `reset_rate_limit()` — INCR + EXPIRE |
| **Create** | `backend/app/services/user_cache.py` | `get_cached_user()` / `set_cached_user()` / `invalidate_user_cache()` |
| **Modify** | `backend/app/core/auth_middleware.py` | Add Redis dep, blacklist check, user cache before DB hit |
| **Modify** | `backend/app/api/v1/auth.py` | Real `POST /logout` + rate-limited `POST /login` |
| **Modify** | `backend/tests/conftest.py` | Add `redis_client` fixture (fakeredis) |
| **Create** | `backend/tests/test_services/test_token_blacklist.py` | Unit tests for blacklist |
| **Create** | `backend/tests/test_services/test_rate_limiter.py` | Unit tests for rate limiter |
| **Create** | `backend/tests/test_services/test_user_cache.py` | Unit tests for user cache |
| **Modify** | `backend/tests/test_api/test_auth.py` | Update `client` fixture + new logout + rate limit tests |
| **Modify** | `backend/tests/test_api/test_editor.py` | Update `client` fixture to override `get_redis` |
| **Modify** | `backend/tests/test_api/test_novel.py` | Update `client` fixture to override `get_redis` |
| **Modify** | `backend/tests/test_api/test_scripts.py` | Update both `client` fixtures to override `get_redis` |
| **Modify** | `backend/tests/test_api/test_tasks.py` | Update `client` fixture to override `get_redis` |

---

### Task 1: Add fakeredis dev dependency

**Files:**
- Modify: `backend/pyproject.toml`

- [ ] **Step 1: Add `fakeredis` to dev dependencies**

```toml
[dependency-groups]
dev = ["fakeredis>=2.32.0"]
```

The `[dependency-groups]` section already exists. Replace its current content:

Current:
```toml
[dependency-groups]
dev = []
```

Replace with:
```toml
[dependency-groups]
dev = ["fakeredis>=2.32.0"]
```

- [ ] **Step 2: Install the new dependency**

```bash
cd backend && uv sync
```

Expected: `fakeredis` and its dependencies installed, `uv.lock` updated.

- [ ] **Step 3: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock
git commit -m "build: add fakeredis dev dependency for Redis testing"
```

---

### Task 2: Redis client foundation (`core/redis.py`)

**Files:**
- Create: `backend/app/core/redis.py`

- [ ] **Step 1: Write the module**

```python
"""Redis connection pool and FastAPI dependency.

Reuses the existing ``REDIS_URL`` from Settings (same instance Celery uses).
All connections are synchronous — matches the rest of the API layer.
"""

from __future__ import annotations

import redis

from app.core.config import settings

# ---------------------------------------------------------------------------
# Connection pool — module-level singleton, opened lazily
# ---------------------------------------------------------------------------

_pool: redis.ConnectionPool | None = None


def _get_pool() -> redis.ConnectionPool:
    """Return the shared connection pool, creating it on first call."""
    global _pool
    if _pool is None:
        _pool = redis.ConnectionPool.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            max_connections=20,
        )
    return _pool


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------


def get_redis():
    """FastAPI dependency — yields a Redis connection per request.

    Usage::

        @router.post("/example")
        def example(r: redis.Redis = Depends(get_redis)):
            r.set("key", "value")
    """
    r = redis.Redis(connection_pool=_get_pool())
    try:
        yield r
    finally:
        r.close()


# ---------------------------------------------------------------------------
# Standalone access (for code that runs outside a request cycle)
# ---------------------------------------------------------------------------


def get_redis_client() -> redis.Redis:
    """Return a Redis client using the shared pool.

    Use this outside of FastAPI request handling (e.g. in Celery tasks
    or startup scripts) where ``Depends()`` is not available.
    """
    return redis.Redis(connection_pool=_get_pool())
```

- [ ] **Step 2: Verify the module imports correctly**

```bash
cd backend && uv run python -c "from app.core.redis import get_redis, get_redis_client; print('OK')"
```

Expected: `OK` (no import errors). Note: the pool is lazy — it won't try to connect to Redis at import time.

- [ ] **Step 3: Commit**

```bash
git add backend/app/core/redis.py
git commit -m "feat: add Redis connection pool and get_redis FastAPI dependency"
```

---

### Task 3: Add `jti` claim to JWTs (`core/security.py`)

**Files:**
- Modify: `backend/app/core/security.py`

- [ ] **Step 1: Read the current create_access_token function to confirm exact line numbers**

The `create_access_token` function is at lines 43-64 of `security.py`. We need to:
1. Add `import uuid` at the top
2. Add `"jti": uuid.uuid4().hex` to the payload dict

- [ ] **Step 2: Add `import uuid`**

At line 8 (after `import logging` and `from datetime import ...`), currently:

```python
import logging
from datetime import datetime, timedelta, timezone

import jwt
from passlib.context import CryptContext
```

Change to:

```python
import logging
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from passlib.context import CryptContext
```

- [ ] **Step 3: Add `jti` to the JWT payload**

In `create_access_token()`, the payload dict is at lines 59-63. Current:

```python
    payload = {
        "sub": user_id,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
```

Replace with:

```python
    payload = {
        "sub": user_id,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "jti": uuid.uuid4().hex,
    }
```

- [ ] **Step 4: Verify — decode a token and check for jti**

```bash
cd backend && uv run python -c "
from app.core.security import create_access_token, decode_access_token
token = create_access_token('test-user-id')
payload = decode_access_token(token)
assert 'jti' in payload, f'jti missing from payload: {payload}'
assert len(payload['jti']) == 32, f'jti wrong length: {len(payload[\"jti\"])}'
print('OK — jti:', payload['jti'])
"
```

Expected: `OK — jti: <32-char-hex>`

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/security.py
git commit -m "feat: add jti (JWT ID) claim to access tokens for blacklisting support"
```

---

### Task 4: Token blacklist service (`services/token_blacklist.py`)

**Files:**
- Create: `backend/app/services/token_blacklist.py`
- Create: `backend/tests/test_services/test_token_blacklist.py`

- [ ] **Step 1: Write the service module**

```python
"""Token blacklist — JWT revocation via Redis.

Each revoked token is stored as a Redis key ``bl:{jti}`` with a TTL equal
to the remaining validity of the token.  Entries auto-expire — no cleanup
job is needed.
"""

from __future__ import annotations

from datetime import datetime, timezone


def blacklist_token(redis_client, jti: str, expires_at: datetime) -> None:
    """Revoke a JWT by adding its *jti* to the blacklist.

    Args:
        redis_client: A ``redis.Redis`` connection.
        jti: The JWT ID from the ``jti`` claim.
        expires_at: The UTC datetime when the JWT expires (``exp`` claim).
    """
    key = f"bl:{jti}"
    ttl = max(1, int((expires_at - datetime.now(timezone.utc)).total_seconds()))
    redis_client.set(key, "1", ex=ttl)


def is_blacklisted(redis_client, jti: str) -> bool:
    """Return ``True`` if *jti* has been revoked."""
    return redis_client.exists(f"bl:{jti}") == 1
```

- [ ] **Step 2: Write the tests**

```python
"""Tests for services/token_blacklist.py — runs entirely in fakeredis."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.token_blacklist import blacklist_token, is_blacklisted


class TestTokenBlacklist:
    """Test JWT token revocation via Redis blacklist."""

    def test_is_blacklisted_returns_false_for_unknown_jti(self, redis_client):
        """A jti that was never blacklisted should return False."""
        assert is_blacklisted(redis_client, "abc123neverblacklisted") is False

    def test_blacklist_then_check(self, redis_client):
        """After blacklisting, is_blacklisted returns True."""
        jti = "test-jti-001"
        expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

        blacklist_token(redis_client, jti, expires_at)
        assert is_blacklisted(redis_client, jti) is True

    def test_blacklist_different_jti_independent(self, redis_client):
        """Blacklisting one jti does not affect another."""
        expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        blacklist_token(redis_client, "jti-A", expires_at)

        assert is_blacklisted(redis_client, "jti-A") is True
        assert is_blacklisted(redis_client, "jti-B") is False

    def test_blacklist_sets_ttl(self, redis_client):
        """The blacklist key should have an expiry set."""
        import time

        jti = "test-jti-ttl"
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=5)

        blacklist_token(redis_client, jti, expires_at)
        ttl = redis_client.ttl(f"bl:{jti}")
        # TTL should be somewhere between 1 and 5 seconds
        assert 1 <= ttl <= 5, f"Expected 1-5s TTL, got {ttl}"

    def test_blacklist_expired_token_sets_min_ttl(self, redis_client):
        """If the token is already expired, TTL floors at 1 second."""
        jti = "test-jti-expired"
        expires_at = datetime.now(timezone.utc) - timedelta(seconds=10)

        blacklist_token(redis_client, jti, expires_at)
        ttl = redis_client.ttl(f"bl:{jti}")
        assert ttl >= 1, f"Expected at least 1s TTL, got {ttl}"
```

- [ ] **Step 3: Run the tests**

```bash
cd backend && uv run pytest tests/test_services/test_token_blacklist.py -v
```

Expected: 5 tests pass.

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/token_blacklist.py backend/tests/test_services/test_token_blacklist.py
git commit -m "feat: add token blacklist service with Redis-backed JWT revocation"
```

---

### Task 5: Rate limiter service (`services/rate_limiter.py`)

**Files:**
- Create: `backend/app/services/rate_limiter.py`
- Create: `backend/tests/test_services/test_rate_limiter.py`

- [ ] **Step 1: Write the service module**

```python
"""Rate limiter — fixed-window counter with Redis INCR + EXPIRE.

Usage::

    allowed, remaining = check_rate_limit(r, "login-email", "user@example.com")
    if not allowed:
        raise HTTPException(status_code=429, detail="Too many attempts")

    # On successful authentication, clear the counters:
    reset_rate_limit(r, "login-email", "user@example.com")
"""

from __future__ import annotations


def check_rate_limit(
    redis_client,
    namespace: str,
    key: str,
    max_requests: int = 5,
    window_seconds: int = 900,
) -> tuple[bool, int]:
    """Increment the counter for *(namespace, key)* and check the limit.

    Args:
        redis_client: A ``redis.Redis`` connection.
        namespace: Rate-limit category (e.g. ``"login-email"``).
        key: Identifier within the namespace (e.g. email address).
        max_requests: Max allowed requests in the window (default 5).
        window_seconds: Window duration in seconds (default 900 = 15 min).

    Returns:
        ``(allowed: bool, remaining: int)`` — *allowed* is ``False`` when
        the limit is exceeded; *remaining* is the count left before the cap.
    """
    redis_key = f"rate:{namespace}:{key}"
    count = redis_client.incr(redis_key)
    if count == 1:
        redis_client.expire(redis_key, window_seconds)
    remaining = max(0, max_requests - count)
    return count <= max_requests, remaining


def reset_rate_limit(redis_client, namespace: str, key: str) -> None:
    """Clear the rate-limit counter for *(namespace, key)*.

    Call this after a successful action (e.g. successful login) so the
    user is not penalised for subsequent operations.
    """
    redis_client.delete(f"rate:{namespace}:{key}")
```

- [ ] **Step 2: Write the tests**

```python
"""Tests for services/rate_limiter.py — runs entirely in fakeredis."""

from __future__ import annotations

from app.services.rate_limiter import check_rate_limit, reset_rate_limit


class TestRateLimiter:
    """Test fixed-window rate limiting."""

    def test_first_request_allowed(self, redis_client):
        """First request in a window should be allowed."""
        allowed, remaining = check_rate_limit(redis_client, "test", "user1")
        assert allowed is True
        assert remaining == 4  # 5 max - 1 = 4 remaining

    def test_hits_limit_then_blocked(self, redis_client):
        """After max_requests hits, the next request is blocked."""
        for i in range(5):
            allowed, remaining = check_rate_limit(
                redis_client, "test", "user2", max_requests=5
            )
            assert allowed is True
            assert remaining == 5 - (i + 1)

        # 6th request — blocked
        allowed, remaining = check_rate_limit(
            redis_client, "test", "user2", max_requests=5
        )
        assert allowed is False
        assert remaining == 0

    def test_different_keys_independent(self, redis_client):
        """Rate limits for different keys are independent."""
        # Exhaust user-a
        for _ in range(5):
            check_rate_limit(redis_client, "login", "user-a", max_requests=5)

        # user-b should still be ok
        allowed, _ = check_rate_limit(redis_client, "login", "user-b", max_requests=5)
        assert allowed is True

        # user-a should be blocked
        allowed, _ = check_rate_limit(redis_client, "login", "user-a", max_requests=5)
        assert allowed is False

    def test_different_namespaces_independent(self, redis_client):
        """Rate limits for different namespaces are independent."""
        # Exhaust login-email
        for _ in range(5):
            check_rate_limit(redis_client, "login-email", "x@test.com", max_requests=5)

        # Same key but different namespace should be ok
        allowed, _ = check_rate_limit(
            redis_client, "login-ip", "x@test.com", max_requests=5
        )
        assert allowed is True

    def test_reset_clears_counter(self, redis_client):
        """After reset, the counter starts fresh."""
        for _ in range(5):
            check_rate_limit(redis_client, "test", "reset-me", max_requests=5)

        reset_rate_limit(redis_client, "test", "reset-me")

        allowed, remaining = check_rate_limit(
            redis_client, "test", "reset-me", max_requests=5
        )
        assert allowed is True
        assert remaining == 4

    def test_window_expires(self, redis_client):
        """After manually expiring the key, counter resets."""
        key = "rate:test:expire-me"
        for _ in range(5):
            check_rate_limit(redis_client, "test", "expire-me", max_requests=5)

        # Manually delete the key to simulate TTL expiry
        assert redis_client.delete(key) == 1

        allowed, remaining = check_rate_limit(
            redis_client, "test", "expire-me", max_requests=5
        )
        assert allowed is True
        assert remaining == 4
```

- [ ] **Step 3: Run the tests**

```bash
cd backend && uv run pytest tests/test_services/test_rate_limiter.py -v
```

Expected: 6 tests pass.

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/rate_limiter.py backend/tests/test_services/test_rate_limiter.py
git commit -m "feat: add fixed-window rate limiter service with Redis INCR+EXPIRE"
```

---

### Task 6: User cache service (`services/user_cache.py`)

**Files:**
- Create: `backend/app/services/user_cache.py`
- Create: `backend/tests/test_services/test_user_cache.py`

- [ ] **Step 1: Write the service module**

```python
"""User profile cache — reduces DB hits for ``get_current_user``.

Cached fields: ``id``, ``username``, ``email``, ``role``, ``is_active``,
``password_hash`` (needed because ``get_current_user`` returns a full
``User`` ORM object that callers may inspect).
"""

from __future__ import annotations

import json

USER_CACHE_TTL = 300  # 5 minutes


def get_cached_user(redis_client, user_id: str) -> dict | None:
    """Return cached user dict or ``None`` on cache miss.

    Args:
        redis_client: A ``redis.Redis`` connection.
        user_id: The user's UUID as a string.

    Returns:
        A dict with keys ``id``, ``username``, ``email``, ``role``,
        ``is_active``, ``password_hash``, or ``None``.
    """
    raw = redis_client.get(f"user:{user_id}")
    if raw is None:
        return None
    return json.loads(raw)


def set_cached_user(redis_client, user_id: str, user_data: dict) -> None:
    """Cache a user profile dict with a 5-minute TTL.

    Args:
        redis_client: A ``redis.Redis`` connection.
        user_id: The user's UUID as a string.
        user_data: Dict with at minimum ``id``, ``username``, ``email``,
            ``role``, ``is_active``, ``password_hash``.
    """
    redis_client.setex(
        f"user:{user_id}",
        USER_CACHE_TTL,
        json.dumps(user_data, ensure_ascii=False),
    )


def invalidate_user_cache(redis_client, user_id: str) -> None:
    """Delete a cached user profile.

    Call this after profile updates (password change, role change, etc.)
    so the next ``get_current_user`` call re-fetches from the DB.
    """
    redis_client.delete(f"user:{user_id}")
```

- [ ] **Step 2: Write the tests**

```python
"""Tests for services/user_cache.py — runs entirely in fakeredis."""

from __future__ import annotations

from app.services.user_cache import (
    get_cached_user,
    invalidate_user_cache,
    set_cached_user,
)


class TestUserCache:
    """Test user profile caching."""

    USER_DATA = {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "username": "testuser",
        "email": "test@example.com",
        "role": "user",
        "is_active": True,
        "password_hash": "$argon2id$fakehash",
    }

    def test_cache_miss_returns_none(self, redis_client):
        """A never-cached user returns None."""
        result = get_cached_user(redis_client, "unknown-user-id")
        assert result is None

    def test_cache_hit_after_set(self, redis_client):
        """Setting then getting returns the same data."""
        uid = self.USER_DATA["id"]
        set_cached_user(redis_client, uid, self.USER_DATA)

        cached = get_cached_user(redis_client, uid)
        assert cached is not None
        assert cached["id"] == uid
        assert cached["username"] == "testuser"
        assert cached["email"] == "test@example.com"
        assert cached["role"] == "user"
        assert cached["is_active"] is True
        assert cached["password_hash"] == "$argon2id$fakehash"

    def test_cache_has_ttl(self, redis_client):
        """The cached entry has a TTL set."""
        uid = self.USER_DATA["id"]
        set_cached_user(redis_client, uid, self.USER_DATA)

        ttl = redis_client.ttl(f"user:{uid}")
        assert 295 <= ttl <= 300, f"Expected ~300s TTL, got {ttl}"

    def test_invalidate_removes_cache(self, redis_client):
        """Invalidate clears the cached entry."""
        uid = self.USER_DATA["id"]
        set_cached_user(redis_client, uid, self.USER_DATA)

        invalidate_user_cache(redis_client, uid)

        cached = get_cached_user(redis_client, uid)
        assert cached is None

    def test_different_users_independent(self, redis_client):
        """Caching user A does not leak to user B."""
        set_cached_user(redis_client, "user-A", self.USER_DATA)

        assert get_cached_user(redis_client, "user-A") is not None
        assert get_cached_user(redis_client, "user-B") is None

    def test_set_overwrites_existing(self, redis_client):
        """Setting a cached user twice overwrites the data."""
        uid = self.USER_DATA["id"]
        set_cached_user(redis_client, uid, self.USER_DATA)

        updated = dict(self.USER_DATA, role="admin")
        set_cached_user(redis_client, uid, updated)

        cached = get_cached_user(redis_client, uid)
        assert cached["role"] == "admin"
```

- [ ] **Step 3: Run the tests**

```bash
cd backend && uv run pytest tests/test_services/test_user_cache.py -v
```

Expected: 6 tests pass.

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/user_cache.py backend/tests/test_services/test_user_cache.py
git commit -m "feat: add user profile cache service with Redis GET/SETEX/DELETE"
```

---

### Task 7: Integrate blacklist + cache into auth middleware (`core/auth_middleware.py`)

**Files:**
- Modify: `backend/app/core/auth_middleware.py`

This is the central integration point. `get_current_user` gains a `Depends(get_redis)` parameter and checks the blacklist + user cache before the DB query.

- [ ] **Step 1: Rewrite `get_current_user` to integrate Redis**

Current function (lines 19-51). Replace the entire `get_current_user` function:

```python
def get_current_user(request: Request, db: Session = Depends(get_db), r: "redis.Redis" = Depends(get_redis)) -> User:
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
```

**Important:** `get_redis` is a FastAPI dependency (generator). In `Depends()` it works because FastAPI handles generators in `Depends()` properly — the generator yields into the endpoint/middleware function. Since `get_redis` is a `def` (not `async def`) generator, and `get_current_user` is also sync, this works correctly.

- [ ] **Step 2: Add the helper functions at module level**

Add these two functions **after** the `require_ownership` function (at the end of the file):

```python
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
```

- [ ] **Step 3: Add the imports at the top**

Current imports (lines 1-16):

```python
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
```

Replace the import block with:

```python
"""Auth middleware — extract the current user from a Bearer token.

All functions are synchronous.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from fastapi import Depends, HTTPException, Request
from redis import Redis
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.redis import get_redis
from app.core.security import decode_access_token
from app.models.sql import User
from app.services.token_blacklist import is_blacklisted
from app.services.user_cache import get_cached_user, set_cached_user

if TYPE_CHECKING:
    pass  # redis.Redis used as type annotation string in Depends
```

Note: `redis.Redis` import is used for the type annotation string `"redis.Redis"` in `Depends(get_redis)` — but actually we can just use the string literal. Let's import `redis` and use `Depends(get_redis)` directly. Actually, the simplest approach: don't annotate the parameter type, or use `Depends(get_redis)` directly without type annotation on `r`.

Let me simplify. The function signature should be:

```python
def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
    r = Depends(get_redis),
) -> User:
```

FastAPI resolves `Depends(get_redis)` to a `redis.Redis` instance. Since we're in a sync context, this just works.

Revised import block:

```python
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
```

This is clean — no need for the `redis` import at all since we don't annotate `r`'s type.

- [ ] **Step 4: Add test fixture that provides redis_client to auth_middleware tests**

Modify `backend/tests/conftest.py` — add a `redis_client` fixture:

First, add the import at the top of `conftest.py` (after line 12, the existing `from app.core.security import ...`):

```python
import fakeredis
from app.core.redis import get_redis
```

Then add the fixture before the `auth_headers` fixture (before line 66):

```python
@pytest.fixture
def redis_client():
    """In-memory fakeredis — isolated per test function."""
    r = fakeredis.FakeRedis(decode_responses=True)
    yield r
    r.flushall()
```

- [ ] **Step 5: Run existing auth tests to verify no regressions**

First, run a quick smoke test:

```bash
cd backend && uv run pytest tests/test_api/test_auth.py::test_me_with_valid_token -v
```

This will FAIL because the `client` fixture in `test_auth.py` doesn't override `get_redis` yet. Expected error: something about `get_redis` not being available. This is expected — we'll update the test fixtures in Task 10.

Mark this step as verified: the error confirms the dependency chain is correctly wired.

- [ ] **Step 6: Commit**

```bash
git add backend/app/core/auth_middleware.py backend/tests/conftest.py
git commit -m "feat: integrate token blacklist + user cache into get_current_user middleware"
```

---

### Task 8: Real logout endpoint (`api/v1/auth.py`)

**Files:**
- Modify: `backend/app/api/v1/auth.py`

- [ ] **Step 1: Replace the stub `POST /logout` with real token blacklisting**

Current logout (lines 124-127):

```python
@router.post("/logout")
def logout():
    """Stub logout endpoint."""
    return BaseResponse(code=200, message="已登出")
```

Replace with:

```python
@router.post("/logout")
def logout(
    request: Request,
    r = Depends(get_redis),
):
    """Invalidate the current JWT by blacklisting its ``jti``.

    Extracts the Bearer token from the Authorization header, decodes it
    to obtain the ``jti`` and ``exp`` claims, then adds the ``jti`` to
    the Redis blacklist with a TTL matching the token's remaining validity.

    If no valid token is provided, the endpoint still returns 200 (no-op)
    to remain backward-compatible with clients that call logout without
    authentication.
    """
    authorization = request.headers.get("Authorization", "")
    token = authorization.removeprefix("Bearer ").strip()
    if token:
        payload = decode_access_token(token)
        if payload is not None:
            jti = payload.get("jti")
            exp = payload.get("exp")
            if jti and exp:
                expires_at = datetime.fromtimestamp(exp, tz=timezone.utc)
                blacklist_token(r, jti, expires_at)

    return BaseResponse(code=200, message="已登出")
```

- [ ] **Step 2: Add the new imports at the top of the file**

Current imports (lines 1-26). After the existing `from app.core.auth_middleware import get_current_user` line, add:

```python
from app.core.redis import get_redis
from app.core.security import decode_access_token
from app.services.token_blacklist import blacklist_token
```

Also add `Request` to the FastAPI import. Current line 11:

```python
from fastapi import APIRouter, Depends, HTTPException
```

Change to:

```python
from fastapi import APIRouter, Depends, HTTPException, Request
```

And add `timezone` to the datetime import. Current line 9:

```python
from datetime import datetime, timezone
```

`timezone` is already imported — good, no change needed.

- [ ] **Step 3: Verify imports**

```bash
cd backend && uv run python -c "from app.api.v1.auth import router; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/v1/auth.py
git commit -m "feat: implement real JWT logout via token blacklist in Redis"
```

---

### Task 9: Rate-limited login (`api/v1/auth.py`)

**Files:**
- Modify: `backend/app/api/v1/auth.py`

- [ ] **Step 1: Update the `POST /login` function to add rate limiting**

Current `login` function (lines 89-117). The function signature currently:

```python
@router.post("/login")
def login(body: LoginRequest, db: Session = Depends(get_db)):
```

Replace the entire function with:

```python
@router.post("/login")
def login(
    body: LoginRequest,
    request: Request,
    db: Session = Depends(get_db),
    r = Depends(get_redis),
):
    """Authenticate user and return a JWT access token.

    Rate-limited: 5 attempts per email + IP per 15-minute window.
    On successful authentication the rate counters are cleared.
    """
    # ── rate limiting ──────────────────────────────────────────
    client_ip = request.client.host if request.client else "unknown"

    allowed_email, _ = check_rate_limit(r, "login-email", body.email)
    allowed_ip, _ = check_rate_limit(r, "login-ip", client_ip)

    if not (allowed_email and allowed_ip):
        raise HTTPException(
            status_code=429,
            detail="登录尝试过于频繁，请15分钟后再试",
            headers={"Retry-After": "900"},
        )

    # ── credential check (existing logic) ──────────────────────
    user = db.execute(
        select(User).where(User.email == body.email)
    ).scalar_one_or_none()

    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="邮箱或密码错误")

    # ── clear rate counters on success ─────────────────────────
    reset_rate_limit(r, "login-email", body.email)
    reset_rate_limit(r, "login-ip", client_ip)

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
```

- [ ] **Step 2: Add the new imports**

Add at the top of `auth.py`, after the existing `from app.services.token_blacklist import blacklist_token` line:

```python
from app.services.rate_limiter import check_rate_limit, reset_rate_limit
```

- [ ] **Step 3: Verify imports**

```bash
cd backend && uv run python -c "from app.api.v1.auth import router; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/v1/auth.py
git commit -m "feat: add rate limiting to login endpoint (5/15min per email+IP)"
```

---

### Task 10: Update test fixtures across all test files to override `get_redis`

**Files:**
- Modify: `backend/tests/test_api/test_auth.py`
- Modify: `backend/tests/test_api/test_editor.py`
- Modify: `backend/tests/test_api/test_novel.py`
- Modify: `backend/tests/test_api/test_scripts.py`
- Modify: `backend/tests/test_api/test_tasks.py`

Every test file that creates a `TestClient` with `dependency_overrides` for `get_db` must now also override `get_redis`. The `redis_client` fixture is already available from `conftest.py`.

- [ ] **Step 1: Update `tests/test_api/test_auth.py`**

Current `client` fixture (lines 23-33):

```python
@pytest.fixture
def client(db: Session):
    """Return a TestClient whose ``get_db`` dependency yields the test session."""

    def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
```

Replace with:

```python
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
```

Also add the import. Current line 14:

```python
from app.core.db import get_db
```

Change to:

```python
from app.core.db import get_db
from app.core.redis import get_redis
```

- [ ] **Step 2: Update `tests/test_api/test_editor.py`**

Need to read the exact fixture code. Current pattern (from the grep output, lines 22-31):

```python
def client(db):
    """TestClient wired to the test database session."""
    ...
    app.dependency_overrides[get_db] = ...
    ...
    app.dependency_overrides.clear()
```

Replace the `client` fixture to:
1. Accept `redis_client` parameter
2. Override `get_redis` in addition to `get_db`
3. Import `get_redis`

Exact replacement — read the file first during execution to confirm line numbers, then:

Add import after `from app.core.db import get_db`:

```python
from app.core.redis import get_redis
```

Update fixture signature and body to:

```python
@pytest.fixture
def client(db, redis_client):
    """TestClient wired to the test database session and fakeredis."""

    def _override_get_db():
        yield db

    def _override_get_redis():
        yield redis_client

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_redis] = _override_get_redis
    with TestClient(app) as tc:
        yield tc
    app.dependency_overrides.clear()
```

- [ ] **Step 3: Update `tests/test_api/test_novel.py`**

Same pattern. Add `from app.core.redis import get_redis` import and update:

```python
@pytest.fixture
def client(db, redis_client):
    """TestClient whose get_db dependency is pointed at the rollback-session."""
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_redis] = lambda: redis_client
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
```

- [ ] **Step 4: Update `tests/test_api/test_scripts.py`**

This file has TWO `client` fixtures. Both need updating. Add `from app.core.redis import get_redis` import.

**Fixture 1** (`client_and_session`, line 41):

```python
@pytest.fixture
def client_and_session(db_engine):
    """TestClient + test Session + auth headers for script mutating tests."""
    ...
    app.dependency_overrides[get_db] = _get_test_db
    ...
```

Update to also override `get_redis`:

Add `redis_client` to the signature and add the override:

```python
@pytest.fixture
def client_and_session(db_engine, redis_client):
    """TestClient + test Session + auth headers for script mutating tests."""
    ...
    def _override_get_redis():
        yield redis_client
    app.dependency_overrides[get_db] = _get_test_db
    app.dependency_overrides[get_redis] = _override_get_redis
    ...
    app.dependency_overrides.clear()
```

**Fixture 2** (`client`, line 63):

```python
@pytest.fixture
def client(db, redis_client):
    """TestClient with get_db override (for GET and public endpoints)."""
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_redis] = lambda: redis_client
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
```

- [ ] **Step 5: Update `tests/test_api/test_tasks.py`**

Current `client` fixture (line 77-79):

```python
@pytest.fixture
def client() -> TestClient:
    """Bare TestClient — no auth."""
    return TestClient(app)
```

This fixture creates a bare TestClient **without** any dependency overrides. However, some tests in this file use `auth_headers` and hit endpoints that use `get_current_user`. Since the `auth_headers` fixture creates a user + JWT, and tests with auth headers will invoke `get_current_user`, the `get_redis` dependency must be available.

For the bare `client` fixture, since it doesn't override `get_db`, it won't need `get_redis` override either for unauthenticated tests. BUT — tests that pass `auth_headers` will need the override. Let me check which tests in `test_tasks.py` use auth_headers...

From the grep output, lines 87, 112, 126, 174, 199, 235 all use `auth_headers`. These tests create tasks which require auth (`get_current_user`), which now requires `get_redis`.

Since the bare `client` doesn't override any deps, when `get_current_user` is called with `Depends(get_redis)`, FastAPI will try to resolve `get_redis` which will try to connect to real Redis. During tests, this will fail.

Solution: Update the `client` fixture to override `get_redis` even though it doesn't override `get_db`:

```python
@pytest.fixture
def client(redis_client) -> TestClient:
    """Bare TestClient with fakeredis override (no DB override)."""
    app.dependency_overrides[get_redis] = lambda: redis_client
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
```

Add `from app.core.redis import get_redis` import.

- [ ] **Step 6: Run all tests to confirm fixtures work**

```bash
cd backend && uv run pytest tests/ -v --ignore=tests/test_db --ignore=tests/test_core --ignore=tests/test_cli --ignore=tests/test_services -k "not stream" 2>&1 | head -80
```

Wait — at this point, all the new service tests should pass. However, the API tests use `auth_headers` which creates a JWT via `create_access_token` — those tokens now have `jti` but since the Redis is fakeredis with no blacklist entries, the middleware will pass. The user cache will be a MISS (fresh fakeredis), so `get_current_user` will fall through to the DB lookup.

**Expected:** All existing tests that don't depend on real Redis pass. The `auth_headers` fixture creates a user in the test DB, so the DB lookup succeeds.

Run the auth tests first:

```bash
cd backend && uv run pytest tests/test_api/test_auth.py -v
```

Expected: 6 tests pass (the 6 existing auth tests). The new logout + rate tests will be added in the next task.

- [ ] **Step 7: Run the full non-CLI test suite**

```bash
cd backend && uv run pytest tests/ -v --ignore=tests/test_cli
```

Expected: All tests that don't require real API keys pass. CLI tests may fail due to missing API keys — those are excluded.

- [ ] **Step 8: Commit**

```bash
git add backend/tests/test_api/test_auth.py backend/tests/test_api/test_editor.py backend/tests/test_api/test_novel.py backend/tests/test_api/test_scripts.py backend/tests/test_api/test_tasks.py
git commit -m "test: update all TestClient fixtures to override get_redis with fakeredis"
```

---

### Task 11: New auth tests — logout and rate limiting

**Files:**
- Modify: `backend/tests/test_api/test_auth.py`

- [ ] **Step 1: Add logout test**

Add after the last existing test in `test_auth.py`:

```python
# ---------------------------------------------------------------------------
# 7. test_logout_blacklists_token
# ---------------------------------------------------------------------------


def test_logout_blacklists_token(client: TestClient):
    """After logging out, the token is blacklisted and GET /me returns 401."""
    tag = uuid.uuid4().hex[:8]
    email = f"logout_{tag}@test.local"
    password = "logoutpass"

    # Register + login
    _register(client, f"logout_{tag}", email, password)
    login_resp = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    token = login_resp.json()["data"]["token"]

    # Token works before logout
    me_before = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me_before.status_code == 200

    # Logout
    logout_resp = client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert logout_resp.status_code == 200
    assert logout_resp.json()["message"] == "已登出"

    # Token no longer works
    me_after = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me_after.status_code == 401
    assert "注销" in me_after.json()["detail"]


# ---------------------------------------------------------------------------
# 8. test_logout_without_token_returns_200
# ---------------------------------------------------------------------------


def test_logout_without_token_returns_200(client: TestClient):
    """Logout without an Authorization header is a no-op (backward compat)."""
    resp = client.post("/api/v1/auth/logout")
    assert resp.status_code == 200
    assert resp.json()["message"] == "已登出"


# ---------------------------------------------------------------------------
# 9. test_login_rate_limit_blocks_after_5_attempts
# ---------------------------------------------------------------------------


def test_login_rate_limit_blocks_after_5_attempts(client: TestClient):
    """After 5 failed login attempts, the 6th returns 429."""
    email = "ratelimit@test.local"

    for i in range(5):
        resp = client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "wrong"},
        )
        assert resp.status_code == 401, f"Attempt {i+1}: expected 401, got {resp.status_code}"

    # 6th attempt should be rate-limited
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "wrong"},
    )
    assert resp.status_code == 429
    assert "频繁" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# 10. test_login_rate_limit_does_not_block_different_email
# ---------------------------------------------------------------------------


def test_login_rate_limit_does_not_block_different_email(client: TestClient):
    """Rate limiting one email does not block another."""
    # Exhaust rate limit for email A
    for _ in range(5):
        client.post(
            "/api/v1/auth/login",
            json={"email": "blocked@test.local", "password": "wrong"},
        )

    # Blocked
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "blocked@test.local", "password": "wrong"},
    )
    assert resp.status_code == 429

    # Different email should still be able to attempt login
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "other@test.local", "password": "wrong"},
    )
    assert resp.status_code == 401  # wrong password, not rate-limited


# ---------------------------------------------------------------------------
# 11. test_login_rate_limit_cleared_on_success
# ---------------------------------------------------------------------------


def test_login_rate_limit_cleared_on_success(client: TestClient):
    """A successful login clears the rate counters."""
    tag = uuid.uuid4().hex[:8]
    email = f"clear_{tag}@test.local"
    password = "rightpass"

    _register(client, f"clear_{tag}", email, password)

    # Do 3 failed attempts
    for _ in range(3):
        client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "wrong"},
        )

    # Successful login
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert resp.status_code == 200
    assert "token" in resp.json()["data"]

    # After success, we should have fresh rate counters.
    # 5 more failed attempts should work (not blocked)
    for i in range(5):
        resp = client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "wrong"},
        )
        assert resp.status_code == 401, f"After reset, attempt {i+1}: expected 401, got {resp.status_code}"

    # 6th should be blocked again
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "wrong"},
    )
    assert resp.status_code == 429
```

- [ ] **Step 2: Run the new tests**

```bash
cd backend && uv run pytest tests/test_api/test_auth.py -v
```

Expected: 11 tests pass (6 existing + 5 new).

- [ ] **Step 3: Run all auth-related tests together**

```bash
cd backend && uv run pytest tests/test_api/test_auth.py tests/test_services/test_token_blacklist.py tests/test_services/test_rate_limiter.py tests/test_services/test_user_cache.py -v
```

Expected: All pass (11 + 5 + 6 + 6 = 28 tests).

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_api/test_auth.py
git commit -m "test: add logout blacklist + login rate limit integration tests"
```

---

### Task 12: Full integration verification

**Files:** None (verification only)

- [ ] **Step 1: Run the complete non-CLI test suite**

```bash
cd backend && uv run pytest tests/ -v --ignore=tests/test_cli
```

Expected: All non-CLI tests pass. The test count should be higher than the original 158 due to the new service + auth tests.

- [ ] **Step 2: Check for key Redis-specific behaviors manually**

```bash
cd backend && uv run python -c "
import fakeredis
from app.services.token_blacklist import blacklist_token, is_blacklisted
from app.services.rate_limiter import check_rate_limit, reset_rate_limit
from app.services.user_cache import get_cached_user, set_cached_user, invalidate_user_cache
from datetime import datetime, timedelta, timezone

r = fakeredis.FakeRedis(decode_responses=True)

# --- Blacklist ---
exp = datetime.now(timezone.utc) + timedelta(hours=1)
blacklist_token(r, 'test-jti', exp)
assert is_blacklisted(r, 'test-jti')
assert not is_blacklisted(r, 'other-jti')
print('blacklist: OK')

# --- Rate limiter ---
for i in range(5):
    ok, rem = check_rate_limit(r, 'ns', 'k', max_requests=5)
    assert ok
ok, rem = check_rate_limit(r, 'ns', 'k', max_requests=5)
assert not ok
reset_rate_limit(r, 'ns', 'k')
ok, rem = check_rate_limit(r, 'ns', 'k', max_requests=5)
assert ok
print('rate_limiter: OK')

# --- User cache ---
uid = 'test-uid'
assert get_cached_user(r, uid) is None
data = {'id': uid, 'username': 'u', 'email': 'e', 'role': 'user', 'is_active': True, 'password_hash': 'h'}
set_cached_user(r, uid, data)
cached = get_cached_user(r, uid)
assert cached == data
invalidate_user_cache(r, uid)
assert get_cached_user(r, uid) is None
print('user_cache: OK')

print('All checks passed!')
"
```

Expected: `All checks passed!`

- [ ] **Step 3: Verify existing tests still pass (regression check)**

```bash
cd backend && uv run pytest tests/test_api/ tests/test_services/ tests/test_core/ tests/test_db/ -v
```

Expected: All pass with zero regressions.

- [ ] **Step 4: Commit (if any changes were made during verification)**

No changes expected. If none:

```bash
echo "Integration verification complete — all tests pass, zero regressions."
```

---

## Completion Checklist

- [ ] 4 new service modules created and tested
- [ ] Redis client foundation in `core/redis.py`
- [ ] `jti` claim in all newly-issued JWTs
- [ ] `POST /logout` actually revokes tokens
- [ ] `POST /login` rate-limited (5 attempts / 15 min)
- [ ] `get_current_user` checks blacklist + user cache
- [ ] All test fixtures updated with fakeredis
- [ ] 28+ new tests (5 blacklist + 6 rate limiter + 6 user cache + 5 auth integration + 6 existing auth)
- [ ] Full test suite passes with zero regressions
- [ ] Only `fakeredis` added to dev dependencies — no new production deps
