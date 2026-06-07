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
