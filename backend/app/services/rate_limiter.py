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
