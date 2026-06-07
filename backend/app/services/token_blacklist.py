"""Token blacklist — JWT revocation via Redis.

Each revoked token is stored as a Redis key ``bl:{jti}`` with a TTL equal
to the remaining validity of the token.  Entries auto-expire — no cleanup
job is needed.

When Redis is unreachable the module degrades gracefully:
- ``is_blacklisted`` returns ``False`` (allow the token — availability
  over strictness).
- ``blacklist_token`` logs a warning and returns (logout is best-effort).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import redis.exceptions

logger = logging.getLogger(__name__)


def blacklist_token(redis_client, jti: str, expires_at: datetime) -> None:
    """Revoke a JWT by adding its *jti* to the blacklist.

    Args:
        redis_client: A ``redis.Redis`` connection.
        jti: The JWT ID from the ``jti`` claim.
        expires_at: The UTC datetime when the JWT expires (``exp`` claim).
    """
    key = f"bl:{jti}"
    ttl = max(1, int((expires_at - datetime.now(timezone.utc)).total_seconds()))
    try:
        redis_client.set(key, "1", ex=ttl)
    except redis.exceptions.ConnectionError:
        logger.warning("Redis unavailable — jti %s NOT blacklisted", jti[:12])


def is_blacklisted(redis_client, jti: str) -> bool:
    """Return ``True`` if *jti* has been revoked.

    When Redis is unreachable this returns ``False`` (optimistic — assume
    the token is valid) so that authentication continues to work.
    """
    try:
        return redis_client.exists(f"bl:{jti}") == 1
    except redis.exceptions.ConnectionError:
        logger.warning("Redis unavailable — skipping blacklist check for jti %s", jti[:12])
        return False
