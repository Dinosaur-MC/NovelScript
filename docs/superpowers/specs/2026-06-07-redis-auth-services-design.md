# Redis-Backed Auth & API Services — Design Spec

**Date:** 2026-06-07
**Status:** Approved
**Scope:** Add token blacklisting (real logout), login rate limiting, and user-profile caching to the FastAPI backend, backed by the existing Redis instance.

---

## 1. Motivation

| Gap | Current Behaviour | Target |
|-----|-------------------|--------|
| Stub logout | `POST /logout` returns success, token stays valid until expiry | Blacklist the JWT's `jti` in Redis so it is immediately invalid |
| DB hit every request | `get_current_user` runs `db.get(User, uid)` on EVERY authenticated call | Cache user profiles in Redis (TTL 300 s), fall back to DB on miss |
| No rate limiting | `POST /login` has no brute-force protection | Sliding-window rate limiter: 5 attempts per key per 15 min window |
| No server-side revocation | A leaked JWT cannot be invalidated | Any blacklisted `jti` is rejected before the DB is touched |

The existing Redis instance (Celery broker + result backend) is reused for all new functionality — no new infrastructure.

---

## 2. Architecture

```
┌─ FastAPI request ────────────────────────────────────────────┐
│                                                               │
│  POST /login  ── rate_limiter ── Redis INCR "rate:login:..." │
│       │                                                       │
│       ▼                                                       │
│  auth_middleware                                              │
│       │                                                       │
│       ├── 1. decode JWT → jti                                │
│       ├── 2. Redis: jti in token_blacklist? → 401           │
│       └── 3. Redis: user:{uid} cache hit? → return          │
│                           miss → DB query → cache set        │
│                                                               │
│  POST /logout ── Redis SADD "token_blacklist" <jti>          │
│                               EXPIREAT <token.exp>            │
└───────────────────────────────────────────────────────────────┘
```

### New Modules

```
backend/app/
├── core/
│   └── redis.py              ← NEW: connection pool + get_redis() dependency
├── services/
│   ├── token_blacklist.py    ← NEW: add/check jti revocation
│   ├── rate_limiter.py       ← NEW: INCR + EXPIRE window
│   └── user_cache.py         ← NEW: get/set/invalidate user profiles
```

### Modified Modules

```
backend/app/
├── core/
│   ├── security.py           ← add jti claim to create_access_token()
│   └── auth_middleware.py    ← check blacklist + user cache before DB
├── api/v1/
│   └── auth.py               ← POST /logout blacklists token; rate limit POST /login
```

---

## 3. Detailed Design

### 3.1 Redis Client (`core/redis.py`)

```python
import redis
from app.core.config import settings

_pool: redis.ConnectionPool | None = None

def _get_pool() -> redis.ConnectionPool:
    global _pool
    if _pool is None:
        _pool = redis.ConnectionPool.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            max_connections=20,
        )
    return _pool

def get_redis():
    """FastAPI dependency — yields a Redis connection per request."""
    r = redis.Redis(connection_pool=_get_pool())
    try:
        yield r
    finally:
        r.close()

def get_redis_client() -> redis.Redis:
    """Standalone (non-DI) access for services that run outside a request."""
    return redis.Redis(connection_pool=_get_pool())
```

**Key decisions:**
- `decode_responses=True` — all values are strings/JSON, no `.decode()` needed
- `max_connections=20` — conservative for a small deployment; tuneable via env
- Connection pool is a module-level singleton, opened lazily
- `get_redis_client()` for Celery tasks that need Redis outside a request cycle

### 3.2 JWT `jti` Claim (`core/security.py`)

Add a unique `jti` (JWT ID) to every token at creation time:

```python
import uuid

def create_access_token(user_id: str, expires_delta=None) -> str:
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(hours=_JWT_EXPIRE_HOURS)
    )
    payload = {
        "sub": user_id,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "jti": uuid.uuid4().hex,          # ← NEW
    }
    return jwt.encode(payload, _JWT_SECRET, algorithm=_JWT_ALGORITHM)
```

The `jti` is a 32-char hex string (UUID4) — unique per issued token. Redis blacklist keys use the format `bl:{jti}`.

### 3.3 Token Blacklist (`services/token_blacklist.py`)

```python
# Redis key prefix: "bl:{jti}" → value "1"
# TTL = remaining seconds until token expiry
# Blacklist entries auto-clean when TTL expires

def blacklist_token(redis_client, jti: str, expires_at: datetime) -> None:
    """Revoke a JWT by adding its jti to the blacklist."""
    key = f"bl:{jti}"
    ttl = max(1, int((expires_at - datetime.now(timezone.utc)).total_seconds()))
    redis_client.set(key, "1", ex=ttl)

def is_blacklisted(redis_client, jti: str) -> bool:
    """Return True if the jti has been revoked."""
    return redis_client.exists(f"bl:{jti}") == 1
```

**Why `SET` + `EX` instead of a global `SADD` set?**
- Per-key TTL means entries auto-expire — no cleanup job needed
- O(1) `EXISTS` check per key
- No risk of a single giant set growing unbounded
- Memory overhead is negligible (~60 bytes per blacklisted token)

### 3.4 Rate Limiter (`services/rate_limiter.py`)

Fixed-window counter with TTL:

```python
def check_rate_limit(
    redis_client,
    namespace: str,
    key: str,
    max_requests: int = 5,
    window_seconds: int = 900,
) -> tuple[bool, int]:
    """
    Returns (allowed: bool, remaining: int).

    Increments the counter. If this is the first hit in the window,
    EXPIRE is set. 429 when limit exceeded.
    """
    redis_key = f"rate:{namespace}:{key}"
    count = redis_client.incr(redis_key)
    if count == 1:
        redis_client.expire(redis_key, window_seconds)
    remaining = max(0, max_requests - count)
    return count <= max_requests, remaining

def reset_rate_limit(redis_client, namespace: str, key: str) -> None:
    """Clear the counter for a given key (e.g. after successful login)."""
    redis_client.delete(f"rate:{namespace}:{key}")
```

**Usage in `POST /login`:**

```python
@router.post("/login")
def login(body: LoginRequest, db: Session = Depends(get_db),
           r: redis.Redis = Depends(get_redis)):
    # Rate limit by email AND by IP (extracted from request)
    allowed_email, remaining_email = check_rate_limit(r, "login-email", body.email)
    allowed_ip, remaining_ip = check_rate_limit(r, "login-ip", client_ip)

    if not (allowed_email and allowed_ip):
        raise HTTPException(
            status_code=429,
            detail="登录尝试过于频繁，请15分钟后再试",
            headers={"Retry-After": "900"},
        )

    # ... existing login logic ...

    # On success: clear rate counters so the user isn't penalised
    reset_rate_limit(r, "login-email", body.email)
    reset_rate_limit(r, "login-ip", client_ip)
```

### 3.5 User Cache (`services/user_cache.py`)

```python
import json

USER_CACHE_TTL = 300  # 5 minutes

def get_cached_user(redis_client, user_id: str) -> dict | None:
    """Return cached user dict or None on miss."""
    raw = redis_client.get(f"user:{user_id}")
    if raw is None:
        return None
    return json.loads(raw)

def set_cached_user(redis_client, user_id: str, user_data: dict) -> None:
    """Cache user profile dict for 5 minutes."""
    redis_client.setex(
        f"user:{user_id}",
        USER_CACHE_TTL,
        json.dumps(user_data, ensure_ascii=False),
    )

def invalidate_user_cache(redis_client, user_id: str) -> None:
    """Delete cached user profile (call after profile updates)."""
    redis_client.delete(f"user:{user_id}")
```

**Cached fields:** `id`, `username`, `email`, `role`, `is_active`, `password_hash`

The `password_hash` is included because `get_current_user` returns the full `User` ORM object, which callers may inspect. Since Redis runs on the same internal network, this is acceptable. If compliance requirements change, we can strip it.

### 3.6 Middleware Changes (`core/auth_middleware.py`)

```python
def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
    r: redis.Redis = Depends(get_redis),
) -> User:
    # 1. Extract + validate JWT
    # 2. Check blacklist (NEW)
    jti = payload.get("jti")
    if jti and is_blacklisted(r, jti):
        raise HTTPException(status_code=401, detail="令牌已被注销")

    # 3. Check user cache (NEW)
    cached = get_cached_user(r, uid_str)
    if cached:
        return _user_from_cache(cached)

    # 4. DB lookup (existing path)
    user = db.get(User, uid)
    if user is None:
        raise HTTPException(status_code=401, detail="用户不存在")

    # 5. Populate cache (NEW)
    set_cached_user(r, uid_str, _user_to_cache(user))

    return user
```

### 3.7 Logout (`api/v1/auth.py`)

```python
@router.post("/logout")
def logout(
    request: Request,
    r: redis.Redis = Depends(get_redis),
):
    """Invalidate the current JWT by blacklisting its jti."""
    authorization = request.headers.get("Authorization", "")
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="缺少认证令牌")

    payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="令牌无效或已过期")

    jti = payload.get("jti")
    exp = payload.get("exp")
    if jti and exp:
        expires_at = datetime.fromtimestamp(exp, tz=timezone.utc)
        blacklist_token(r, jti, expires_at)

    return BaseResponse(code=200, message="已登出")
```

---

## 4. Dependencies

Add to `pyproject.toml`:

```toml
# Production
"redis>=6.4.0",       # Redis client for Python (already listed in dependencies!)

# Dev (testing)
"fakeredis[lua]>=2.32.0",
```

`redis` is already in `pyproject.toml` (line: `"redis>=6.4.0"`). Only `fakeredis` needs to be added to `dev` dependencies.

---

## 5. Test Strategy

### Fixtures (`tests/conftest.py` — additions)

```python
import fakeredis

@pytest.fixture
def redis_client():
    """In-memory Redis mock — resets between tests."""
    server = fakeredis.FakeServer()
    r = fakeredis.FakeRedis(server=server, decode_responses=True)
    yield r
    r.flushall()

@pytest.fixture
def client(db, redis_client):
    """TestClient with Redis dependency override."""
    def _override_get_redis():
        yield redis_client

    app.dependency_overrides[get_db] = lambda: db  # (yield-style simplified)
    app.dependency_overrides[get_redis] = _override_get_redis
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
```

### New Tests

| Test | What it verifies |
|------|-----------------|
| `test_logout_blacklists_token` | After logout, GET /me with same token returns 401 |
| `test_blacklisted_token_401` | Manually blacklisted jti → 401 |
| `test_login_rate_limit_429` | 6 rapid login attempts → 429 on #6 |
| `test_rate_limit_resets_on_success` | Successful login clears rate counters |
| `test_user_cache_hit` | Second request with same token skips DB |
| `test_user_cache_expires` | After TTL, DB is re-queried |
| `test_register_clears_cache` | Not applicable — register creates new user, no cache to clear |
| `test_blacklist_ttl_auto_clean` | After TTL, jti no longer in Redis (fakeredis) |

Existing auth tests continue to pass — `get_current_user`'s new Redis dependency resolves transparently via `fakeredis`.

---

## 6. Configuration

No new env vars. All Redis config reuses `REDIS_URL` from `Settings`.

| Setting | Default | Notes |
|---------|---------|-------|
| `REDIS_URL` | `redis://localhost:6379/0` | Existing — Celery broker + backend |
| Rate limit window | 900 s (15 min) | Hardcoded — could become `AUTH_RATE_LIMIT_WINDOW` later |
| Rate limit max | 5 attempts | Hardcoded — could become `AUTH_RATE_LIMIT_MAX` later |
| User cache TTL | 300 s (5 min) | Hardcoded — could become `USER_CACHE_TTL` later |
| Redis pool max | 20 connections | Hardcoded in `_get_pool()` |

Tip: Celery uses Redis DB 0 (broker) + DB 0 (result backend). The new auth services also use DB 0. At this scale there is no practical risk of key collision — all keys are prefixed (`bl:`, `rate:`, `user:`). If traffic grows, separate Redis DBs (`/1`) can be added via config.

---

## 7. Migration & Rollback

**Forward migration path:** None. All new keys are ephemeral (TTL-based). No schema changes.

**Rollback:** Remove `get_redis` from `get_current_user` + `POST /logout` signatures, revert `create_access_token` to not include `jti`. Deploy. Zero data loss — Redis keys just expire.

---

## 8. Open Questions / Future Work

- **Phase 2**: Response caching for `GET /tasks` and `GET /novels` (list endpoints) — TTL 30 s, invalidated on write
- **Phase 2**: GraphRAG query result caching in editor chat (`POST /editor/chat/{task_id}`)
- **Phase 3**: Redis-backed session store for multi-device logout (track all active `jti`s per user)
- **Phase 3**: Configurable rate limits per endpoint, not just login
