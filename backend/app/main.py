import asyncio
from contextlib import asynccontextmanager

from starlette.exceptions import HTTPException
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import logging

from app.models.http import BaseResponse, ErrorResponse

# 配置日志
logging.basicConfig(
    level=logging.DEBUG,
    format="[%(asctime)s] %(name)s - %(levelname)s: %(message)s",
    encoding="utf-8",
)
logger = logging.getLogger(__name__)

# 后台 watcher 控制
_pipeline_watcher_task: asyncio.Task | None = None
_simple_queue_task: asyncio.Task | None = None
_WATCHER_INTERVAL = 5  # seconds
_CONSUMED_MARKER_PREFIX = "pipeline:consumed:"


async def _pipeline_result_watcher():
    """Background watcher — persists completed pipeline results to DB.

    Celery writes results to Redis.  This watcher runs in the Main process,
    periodically checks Redis for unpersisted results, and writes them
    to the database.  Guarantees delivery even when no SSE client is connected.

    Data flow:  Celery → Redis ← Main (watcher) → DB
    """
    from app.services.pipeline_dto import (
        REDIS_RESULT_PREFIX,
        REDIS_RESULT_TTL,
        load_pipeline_result,
    )
    from app.services.pipeline_executor import persist_pipeline_output

    logger.info("Pipeline result watcher started (interval=%ds).", _WATCHER_INTERVAL)

    while True:
        try:
            await asyncio.sleep(_WATCHER_INTERVAL)

            # Get a Redis connection (sync in background thread is fine)
            from app.core.redis import get_redis_client

            redis_conn = get_redis_client()
            if redis_conn is None:
                continue

            # Scan for pipeline result keys
            cursor = 0
            while True:
                cursor, keys = redis_conn.scan(
                    cursor=cursor,
                    match=f"{REDIS_RESULT_PREFIX}*",
                    count=200,
                )
                for key in keys:
                    task_id = key.replace(REDIS_RESULT_PREFIX, "")
                    try:
                        # Skip if already consumed (marker exists)
                        if redis_conn.exists(f"{_CONSUMED_MARKER_PREFIX}{task_id}"):
                            continue

                        output = load_pipeline_result(redis_conn, task_id)
                        if output is None:
                            continue

                        from app.core.db import _session_factory

                        session = _session_factory()
                        try:
                            import uuid
                            persist_pipeline_output(
                                session,
                                output,
                                uuid.UUID(task_id),
                                uuid.UUID(output.novel_id) if output.novel_id else uuid.UUID(task_id),
                            )
                            # Set consumed marker (do NOT delete result key — SSE
                            # may still need to read script_id from it).
                            redis_conn.setex(
                                f"{_CONSUMED_MARKER_PREFIX}{task_id}",
                                3600,  # 1h — matches Celery result_expires
                                "1",
                            )
                            from app.services.task_lock import release_task_lock
                            release_task_lock(task_id)
                            logger.info(
                                "Watcher: persisted task %s (status=%s).",
                                task_id, output.status,
                            )
                        except Exception:
                            session.rollback()
                            logger.exception(
                                "Watcher: failed to persist task %s.", task_id,
                            )
                        finally:
                            session.close()
                    except Exception:
                        logger.exception("Watcher: error processing key %s.", key)

                if cursor == 0:
                    break

        except asyncio.CancelledError:
            logger.info("Pipeline result watcher cancelled.")
            break
        except Exception:
            logger.exception("Pipeline result watcher error (will retry).")


# ========== 生命周期 ==========

@asynccontextmanager
async def _lifespan(_app: FastAPI):
    """Startup / shutdown hook — init DB, start watchers, dispose on shutdown."""
    global _pipeline_watcher_task, _simple_queue_task

    # Startup
    from app.core.db import init_db
    init_db()
    logger.info("Database initialised.")

    # Start background pipeline result watcher (guaranteed persistence)
    _pipeline_watcher_task = asyncio.create_task(_pipeline_result_watcher())
    logger.info("Pipeline result watcher launched.")

    # Start simple queue worker (Celery fallback — processes tasks in-process)
    try:
        from app.services.simple_queue import worker_loop
        _simple_queue_task = asyncio.create_task(worker_loop())
        logger.info("Simple queue worker launched (Celery fallback).")
    except Exception as exc:
        logger.warning("Failed to start simple queue worker: %s", exc)

    yield

    # Shutdown
    if _simple_queue_task:
        _simple_queue_task.cancel()
        try:
            await _simple_queue_task
        except asyncio.CancelledError:
            pass
        _simple_queue_task = None

    if _pipeline_watcher_task:
        _pipeline_watcher_task.cancel()
        try:
            await _pipeline_watcher_task
        except asyncio.CancelledError:
            pass
        _pipeline_watcher_task = None

    from app.core.db import dispose_engine
    dispose_engine()
    logger.info("Engine pool disposed.")


# ========== 创建主应用实例 ==========
app = FastAPI(
    title="NovelScript API",
    description="NovelScript (析幕) — AI 驱动的长篇小说到结构化剧本转换系统",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    debug=True,
    lifespan=_lifespan,
)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    logger.error(f"HTTP 异常：{str(exc)}", exc_info=True)
    import traceback
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(
            code=exc.status_code,
            message=exc.detail,
            detail=traceback.format_exc() if app.debug else None,
        ).model_dump(exclude_none=True),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.error(f"未处理的异常：{str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            code=500,
            message="Internal Server Error",
            detail=str(exc) if app.debug else None,
        ).model_dump(exclude_none=True),
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ========== 路由注册 ==========
from app.api import api_v1_router

app.include_router(api_v1_router)


@app.get("/health", tags=["Health"])
async def health_check():
    return BaseResponse(code=200, message="健康检查通过", data={"status": "healthy"})


@app.head("/", tags=["Root"])
async def root_head():
    return Response()
