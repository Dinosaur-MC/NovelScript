"""Celery application — factory for background task workers.

Usage
-----
Start a worker::

    celery -A app.core.celery_app worker --loglevel=info

Start with concurrency control::

    celery -A app.core.celery_app worker --concurrency=2 --loglevel=info

The worker runs in a **separate process** from the FastAPI server.
Pipeline tasks dispatched via ``.apply_async()`` land in Redis, are
picked up by the worker, and report progress via ``self.update_state()``
(also Redis).  The SSE endpoint reads progress from Redis via
``AsyncResult(task_id)`` — no in-process queue is needed.
"""

from __future__ import annotations

from celery import Celery

from app.core.config import settings

# Broker + result backend — both Redis.
# Override via .env: CELERY_BROKER_URL=redis://your-host:6379/0
REDIS_URL = settings.REDIS_URL

celery_app = Celery(
    "novelscript",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["app.tasks.pipeline"],
)

# ---------------------------------------------------------------------------
# Defaults — sane for pipeline workloads (long-running, low traffic)
# ---------------------------------------------------------------------------
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,          # re-deliver if worker crashes mid-task
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,  # one task at a time (LLM-heavy)
    result_expires=3600,           # keep results for 1 hour
    broker_connection_retry_on_startup=True,
)
