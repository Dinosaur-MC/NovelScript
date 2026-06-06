# ============================================================================
# NovelScript Backend — multi-stage Docker build (Python 3.13 + uv)
# ============================================================================
# Build target:
#   docker build -t novelscript-backend .
#
# Two targets are available:
#   1. api    — FastAPI server     (default)
#   2. worker — Celery background worker
#
#   docker build --target api    -t novelscript-api    .
#   docker build --target worker -t novelscript-worker .
# ============================================================================

# ---------------------------------------------------------------------------
# Stage 1 — uv environment (cache mounts for uv + apt)
# ---------------------------------------------------------------------------
FROM python:3.13.13-slim AS build

# Install uv via the official image (fast, pinned)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Copy dependency manifests first → cache layer when deps don't change
COPY pyproject.toml uv.lock ./

# --mount=type=cache keeps uv packages + apt lists across rebuilds
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# ---------------------------------------------------------------------------
# Stage 2 — application code
# ---------------------------------------------------------------------------
FROM python:3.13.13-slim AS app-base

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    # psycopg2 binary needs libpq at runtime
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy uv binary + virtual environment
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
COPY --from=build /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" \
    VIRTUAL_ENV="/app/.venv" \
    PYTHONUNBUFFERED=1

# Copy application source
COPY . .

# ---------------------------------------------------------------------------
# Target: api — FastAPI server (default)
# ---------------------------------------------------------------------------
FROM app-base AS api

EXPOSE 8000

# uvicorn with production-grade settings:
#   --no-access-log   reduces noise in container logs
#   --proxy-headers   trusts X-Forwarded-* from nginx / Traefik
CMD ["uv", "run", "--no-sync", "uvicorn", "app.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--no-access-log", "--proxy-headers"]

# ---------------------------------------------------------------------------
# Target: worker — Celery background task runner
# ---------------------------------------------------------------------------
FROM app-base AS worker

# Celery worker with concurrency tuned for LLM workloads
#   --concurrency=2   one LLM-heavy task per worker process is enough
CMD ["celery", "-A", "app.core.celery_app", "worker", \
     "--loglevel=info", "--concurrency=2", \
     "--prefetch-multiplier=1"]
