"""Distributed task lock — prevents double-dispatch when Celery and simple queue coexist.

Ensures a single pipeline task is never processed by more than one worker,
even when Celery recovers mid-queue::

  1. Before dispatch (Celery or simple queue), acquire Redis lock via SET NX
  2. Lock TTL matches Celery's expires (2h) — auto-released if worker crashes
  3. Before processing, simple queue worker re-checks the lock
  4. On completion / failure, release the lock
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_LOCK_PREFIX = "pipeline:lock:"
_DEFAULT_TTL = 7200  # 2 hours — matches Celery expires


def try_acquire_task_lock(task_id: str, ttl: int = _DEFAULT_TTL) -> bool:
    """Try to acquire a distributed lock for *task_id*.

    Uses Redis ``SET NX EX`` — only succeeds if no lock exists.
    Returns True if the lock was acquired (caller should proceed),
    False if another worker already holds the lock.
    """
    try:
        from app.core.redis import get_redis_client

        r = get_redis_client()
        if r is None:
            logger.warning("Redis unavailable — cannot acquire task lock for %s.", task_id)
            return True  # Pessimistic: allow execution without Redis

        key = f"{_LOCK_PREFIX}{task_id}"
        acquired = r.set(key, "1", nx=True, ex=ttl)
        if acquired:
            logger.debug("Task lock acquired for %s.", task_id)
        else:
            logger.info("Task %s is already locked — another worker is processing it.", task_id)
        return bool(acquired)
    except Exception as exc:
        logger.warning("Failed to acquire task lock for %s: %s", task_id, exc)
        return True  # Pessimistic: allow execution on error


def release_task_lock(task_id: str) -> None:
    """Release the distributed lock for *task_id*."""
    try:
        from app.core.redis import get_redis_client

        r = get_redis_client()
        if r is None:
            return

        key = f"{_LOCK_PREFIX}{task_id}"
        r.delete(key)
        logger.debug("Task lock released for %s.", task_id)
    except Exception as exc:
        logger.warning("Failed to release task lock for %s: %s", task_id, exc)


def is_task_locked(task_id: str) -> bool:
    """Check if a task lock exists (without acquiring)."""
    try:
        from app.core.redis import get_redis_client

        r = get_redis_client()
        if r is None:
            return False
        return bool(r.exists(f"{_LOCK_PREFIX}{task_id}"))
    except Exception:
        return False
