"""Rate limiter — fixed-window counter with Redis INCR + EXPIRE.

Usage::

    allowed, remaining = check_rate_limit(r, "login-email", "user@example.com")
    if not allowed:
        raise HTTPException(status_code=429, detail="Too many attempts")

    # On successful authentication, clear the counters:
    reset_rate_limit(r, "login-email", "user@example.com")

When Redis is unreachable the module degrades gracefully:
- ``check_rate_limit`` returns ``(True, max_requests)`` — all requests
  are allowed (availability over rate limiting).
- ``reset_rate_limit`` is a silent no-op.
"""

from __future__ import annotations

import logging

import redis.exceptions

logger = logging.getLogger(__name__)


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
        When Redis is unreachable, returns ``(True, max_requests)``.
    """
    redis_key = f"rate:{namespace}:{key}"
    try:
        # Atomically create the key with TTL if it doesn't exist.
        # SETNX + EX ensures the key always has an expiry, eliminating
        # the INCR-then-EXPIRE race window where a crash would leak a
        # permanent key.
        redis_client.set(redis_key, "0", nx=True, ex=window_seconds)
        count = redis_client.incr(redis_key)
        remaining = max(0, max_requests - count)
        return count <= max_requests, remaining
    except redis.exceptions.ConnectionError:
        logger.warning(
            "Redis unavailable — rate limit bypassed for %s:%s",
            namespace, key[:40],
        )
        return True, max_requests


def reset_rate_limit(redis_client, namespace: str, key: str) -> None:
    """Clear the rate-limit counter for *(namespace, key)*.

    Call this after a successful action (e.g. successful login) so the
    user is not penalised for subsequent operations.
    When Redis is unreachable this is a silent no-op.
    """
    try:
        redis_client.delete(f"rate:{namespace}:{key}")
    except redis.exceptions.ConnectionError:
        logger.warning(
            "Redis unavailable — rate limit reset skipped for %s:%s",
            namespace, key[:40],
        )
