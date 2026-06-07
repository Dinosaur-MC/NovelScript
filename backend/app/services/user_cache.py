"""User profile cache — reduces DB hits for ``get_current_user``.

Cached fields: ``id``, ``username``, ``email``, ``role``, ``is_active``,
``password_hash`` (needed because ``get_current_user`` returns a full
``User`` ORM object that callers may inspect).

When Redis is unreachable the module degrades gracefully:
- ``get_cached_user`` returns ``None`` (cache miss → fall through to DB).
- ``set_cached_user`` and ``invalidate_user_cache`` are silent no-ops.
"""

from __future__ import annotations

import json
import logging

import redis.exceptions

logger = logging.getLogger(__name__)

USER_CACHE_TTL = 300  # 5 minutes


def get_cached_user(redis_client, user_id: str) -> dict | None:
    """Return cached user dict or ``None`` on cache miss.

    Args:
        redis_client: A ``redis.Redis`` connection.
        user_id: The user's UUID as a string.

    Returns:
        A dict with keys ``id``, ``username``, ``email``, ``role``,
        ``is_active``, ``password_hash``, or ``None``.
        Returns ``None`` when Redis is unreachable.
    """
    try:
        raw = redis_client.get(f"user:{user_id}")
    except redis.exceptions.ConnectionError:
        logger.warning("Redis unavailable — user cache miss for %s", user_id[:12])
        return None
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

    When Redis is unreachable this is a silent no-op — the next request
    will perform a DB lookup as a cache miss.
    """
    try:
        redis_client.setex(
            f"user:{user_id}",
            USER_CACHE_TTL,
            json.dumps(user_data, ensure_ascii=False),
        )
    except redis.exceptions.ConnectionError:
        logger.warning("Redis unavailable — user cache write skipped for %s", user_id[:12])


def invalidate_user_cache(redis_client, user_id: str) -> None:
    """Delete a cached user profile.

    Call this after profile updates (password change, role change, etc.)
    so the next ``get_current_user`` call re-fetches from the DB.

    When Redis is unreachable this is a silent no-op — the cache entry
    will expire naturally via TTL.
    """
    try:
        redis_client.delete(f"user:{user_id}")
    except redis.exceptions.ConnectionError:
        logger.warning("Redis unavailable — user cache invalidation skipped for %s", user_id[:12])
