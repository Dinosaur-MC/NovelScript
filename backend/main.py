"""NovelScript backend — development entry point.

Usage::

    uv run main.py                  # development: API + Celery worker
    uv run uvicorn app.main:app ... # production: API only (Celery separate)

When ``DEBUG=true`` (default for development), this script also starts a
Celery background worker as a subprocess so you don't need a separate
terminal.  On Windows the worker uses ``--pool=solo`` because the default
``prefork`` pool is not supported.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time

from dotenv import load_dotenv

load_dotenv()


def _start_celery_worker() -> subprocess.Popen | None:
    """Launch a Celery worker subprocess for development.

    Returns the :class:`Popen` handle so the main process can terminate it
    on shutdown.  Returns ``None`` if Celery is not needed (production).
    """
    if os.getenv("CELERY_DEV_DISABLE", "").lower() in ("1", "true", "yes"):
        return None

    celery_concurrency = os.getenv("CELERY_DEV_CONCURRENCY", "2")

    # Windows: prefork pool is broken — default to threads
    is_windows = sys.platform == "win32"
    default_pool = "threads" if is_windows else "prefork"
    pool = os.getenv("CELERY_DEV_POOL", default_pool)

    cmd = [
        sys.executable, "-m", "celery",
        "-A", "app.core.celery_app",
        "worker",
        "--loglevel=info",
        "--concurrency", celery_concurrency,
        "--pool", pool,
    ]
    print(f"[main] Starting Celery worker (pool={pool}, concurrency={celery_concurrency}) …")
    return subprocess.Popen(cmd)


def main():
    print("=" * 60)
    print("  NovelScript Backend — Development Server")
    print("=" * 60)

    # -- Celery worker (development) --------------------------------------------------
    celery_proc = _start_celery_worker()

    # -- FastAPI ----------------------------------------------------------------------
    import uvicorn

    is_debug = os.getenv("DEBUG", "true").lower() in ("1", "true", "yes")
    print(f"[main] Starting FastAPI on http://0.0.0.0:8000 (DEBUG={is_debug})")

    try:
        uvicorn.run(
            "app.main:app",
            host="0.0.0.0",
            port=8000,
            reload=is_debug,
            reload_dirs="app" if is_debug else None,  # type: ignore[arg-type]
        )
    finally:
        if celery_proc is not None:
            print("[main] Shutting down Celery worker …")
            celery_proc.terminate()
            try:
                celery_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                celery_proc.kill()
                celery_proc.wait()
            print("[main] Celery worker stopped.")


if __name__ == "__main__":
    main()
