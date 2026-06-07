# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

NovelScript (析幕) is an AI-driven pipeline that converts long-form novels (3+ chapters) into structured scripts compliant with film industry standards (Fountain 1.1 / YAML). The system emphasizes **deterministic pipelines over probabilistic LLM outputs** — strict validation, bidirectional source tracing, and an All-in-One PostgreSQL data layer anchor the AI's creativity.

## Development Status

See `.temp/DEVELOPMENT_STATUS.md` for frontend status (51 files, 3 routes, 6 API modules, 6 Zustand stores, 6 hooks, 52 tests).

### Backend Status Summary

| Layer | Status |
|-------|--------|
| Pipeline CLI | ✅ Complete — 7 stages, JSON mode, retry, paragraph splitter, chapter summaries, narrative summary, directory input |
| Database | ✅ Complete — 9 tables, pgvector HNSW, pg_trgm, sync psycopg2, KG persistence, embedding caching |
| API (25 endpoints) | ✅ Complete — auth (JWT+argon2, ownership checks), novels, scripts, tasks (SSE), editor (GraphRAG-enhanced) |
| Pipeline ↔ DB Integration | ✅ Complete — Celery worker (Redis broker), SSE via AsyncResult polling, DB chapters + KG cache preferred |
| Background Tasks | ✅ Complete — Celery + Redis replaces daemon threads; run_pipeline.apply_async() |
| Auth & Security | ✅ Complete — get_current_user dependency, require_ownership helper on all write endpoints |
| Tests | ✅ 158 passing, 0 skipped |
| Docker | ✅ Complete — multi-stage Dockerfile (api/worker targets), docker-compose (prod/dev profiles) |

**API URL tree:** `/api/v1/auth/*` `/novels/` `/scripts/` `/tasks/` `/editor/`  (all write endpoints use auth middleware)

### Pipeline Stages (v0.2.0)

```
1. Chunking      — regex split (第X章), LLM fallback (Flash)
2. Summarize     — per-chapter objective summary (Flash, parallel)
3. RAG Index     — FAISS via OpenRouter text-embedding-3-small
4. GraphRAG      — KG extraction (Pro, with RAG cross-chapter context)
   • Single-shot  (≤5 chapters): all chapters in one prompt
   • Incremental  (>5 chapters): chapter-by-chapter with prior-entity context
5. Conversion    — chapter → scenes (Flash, parallel, paragraph-group input + chapter summaries)
6. Optimization  — cross-scene consistency (Pro, batched by scene)
7. Narrative Summary — story overview from chapter summaries (Flash)
→ Export (YAML/JSON)
→ DB Cache: chapters + embeddings + KG persisted for reuse
```

### Pipeline Input Modes

```
1. Single file   → regex split → LLM fallback → run_from_chapters()
2. Directory      → each .txt = one chapter (chunking skipped)
3. DB chapters    → _load_chapters() (chunking skipped)
```

### LLM Architecture

- **Models**: DeepSeek V4 Pro (1M context, 384K output) / Flash (1M context, 384K output)
- **JSON mode**: `response_format: {type: json_object}`, NOT OpenAI json_schema
- **Retry**: Application-layer exponential backoff with jitter (per-stage: 1-3 retries)
- **Context budget**: Auto-detected from model name + `.env` overrides (`LLM_CONTEXT_WINDOW`, `LLM_MAX_OUTPUT_TOKENS`)
- **Concurrency**: `asyncio.Semaphore` gates concurrent LLM calls (default 20, configurable via `LLM_MAX_CONCURRENCY` or `-c` CLI flag)
- **Paragraph splitter**: Boundary-aware (`\n\n+`), short paragraphs (≤32 chars) merged
- **OpenRouter**: Embeddings only — `nvidia/llama-nemotron-embed-vl-1b-v2:free` via `https://openrouter.ai/api/v1/embeddings`

Full CLI documentation: `backend/cli/README.md`

### Key CLI Options

```
uv run python -m cli.pipeline <input> [-o output.yaml] [--json] [-n N] [-c C] [-s STYLE]
uv run python -m cli.pipeline chapters/ -o out.yaml -n 3  # first 3 chapters, dir mode
```

| Flag | Description | Default |
|------|-------------|---------|
| `-o`, `--output` | Write result to file instead of stdout | stdout |
| `--json` | Export JSON instead of YAML | YAML |
| `-n N`, `--limit N` | Process only the first N chapters | all |
| `-c C`, `--concurrency C` | Max concurrent LLM API calls | 20 |
| `-s STYLE`, `--style STYLE` | AI scriptwriting direction injected into conversion prompts | (none) |

## Package Managers

| Layer    | Tool   | Lock File        |
| -------- | ------ | ---------------- |
| Backend  | `uv`   | `backend/uv.lock` |
| Frontend | `pnpm` | `frontend/pnpm-lock.yaml` |

Work in the corresponding subdirectory (`backend/` or `frontend/`) before running package manager commands.

## Common Commands

### Backend (Python 3.13)

```bash
cd backend
uv sync                                         # Install dependencies
uv run main.py                                  # Start dev server (uvicorn, port 8000, reload on DEBUG)

# Celery Worker (separate terminal — required for pipeline tasks):
celery -A app.core.celery_app worker --loglevel=info --concurrency=2

uv run pytest                                   # Run tests (158 passing)
uv run python -m cli.pipeline <input.txt>       # Pipeline standalone (no DB)
uv run python -m cli.pipeline chapters/ -o out.yaml  # Directory input
uv add <package>                                # Add a dependency
```

### Docker

```bash
# Production (internal network, only frontend :3000 exposed)
docker compose up -d --build

# Development (exposes API :8000, DB :5432, Redis :6379)
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build

# Scale workers for parallel pipelines
docker compose up -d --scale worker=3

# Teardown
docker compose down -v
```

### Frontend (React 19 + React Router 7, Node 24)

```bash
cd frontend
pnpm install                                    # Install dependencies
pnpm run dev                                    # Start dev server (Vite HMR, port 5173)
pnpm run build                                  # Production build (SSR)
pnpm run start                                  # Serve production build
pnpm run typecheck                              # TypeScript type checking
pnpm run test                                   # Vitest (52 tests)
```

## Architecture

### Backend (`backend/app/`)

```
app/
├── main.py                # FastAPI app factory — lifespan, CORS, exception handlers
├── api/v1/                # 25 endpoints: auth, novels, scripts, tasks, editor
│   ├── __init__.py        # Single router tree → /api/v1/*
│   ├── auth.py            # register, login, logout, me (JWT + argon2)
│   ├── novels.py          # upload (JSON/file, auto-create Task), list, get, update, delete
│   ├── scripts.py         # list, get, update (YAML validate), delete, export
│   ├── tasks.py           # create, list, stream (SSE via AsyncResult), status, update, resume, get
│   └── editor.py          # chat (LLM + GraphRAG context), apply_patch (RFC 6901), undo
├── core/
│   ├── config.py          # pydantic-settings — DATABASE_URL, REDIS_URL, API keys, ADMIN_*
│   ├── db.py              # Sync engine (psycopg2), session, get_db(), init_db(),
│   │                      #   dispose_engine(), _seed_admin(), recover_stale_tasks()
│   ├── security.py        # argon2 hashing, JWT create/decode, configure_jwt()
│   ├── auth_middleware.py # get_current_user dependency, require_ownership helper
│   └── celery_app.py      # Celery singleton (Redis broker + backend)
├── tasks/
│   └── pipeline.py        # Celery task: run_pipeline with self.update_state() for SSE
├── models/
│   ├── http.py            # BaseResponse(code, message, data), ErrorResponse
│   └── sql.py             # 9 SQLModel tables (users…audit_logs)
├── services/
│   ├── base.py            # BaseCRUD[T] — create/get/list/update/delete
│   ├── progress.py        # ProgressManager no-op compat stub
│   ├── pipeline_executor.py  # DB cache helpers (no threading): _load_chapters,
│   │                      #   _load_cached_kg, _persist_kg, _persist_embeddings, _persist_chapters
│   └── sse.py             # push_progress() → ProgressManager (deprecated)
├── db/
│   └── init.sql           # 9-table DDL, 3 extensions, HNSW + GIN indexes
└── cli/                   # Pipeline engine — 11 modules
    ├── models.py          # Chapter, ParagraphGroup, Scene, Script, KG, etc.
    ├── chunker.py         # Regex (第X章) + LLM fallback with JSON mode
    ├── paragraph_splitter.py  # Boundary-aware paragraph grouping (≤32-char merge)
    ├── summarizer.py      # Per-chapter objective summary (Flash, 100-200 chars, anti-markdown)
    ├── rag_builder.py     # FAISS index, keyword fallback, embed_texts(), build_index_from_db_embeddings()
    ├── graphrag_builder.py # KG extraction: single-shot + incremental (chapter-by-chapter with entity dedup)
    ├── converter.py       # Chapter → scenes (Flash, paragraph groups, chapter_summary)
    ├── optimizer.py       # Batch consistency check (Pro, position-based source_ref restore)
    ├── llm_router.py      # Model routing, context/output limits, invoke_with_retry()
    ├── exporter.py        # to_yaml(), to_json()
    └── pipeline.py        # Orchestrator: run(), run_from_chapters(), run_from_text()
                           #   Optional faiss_index + kg params for cached reuse
```

**Key architectural patterns**:
- **Celery + Redis**: Pipeline execution delegated to separate worker processes via `run_pipeline.apply_async()`.  No in-process daemon threads.
- **SSE via AsyncResult**: SSE endpoint polls `AsyncResult(task_id).state/.info` from Redis (every 500ms).  No in-process `queue.Queue`.
- **DB Cache**: Chapter embeddings (1536-dim) + KG nodes/edges persisted to DB after first run.  Subsequent pipeline runs skip API calls.
- **Dual-model routing**: `deepseek-v4-pro` for GraphRAG + optimization; `deepseek-v4-flash` for chunking, summarization, conversion, AI chat
- **All-in-One DB**: PostgreSQL 18, 9 tables, sync psycopg2 (not asyncpg), no separate vector/graph DB
- **pgvector HNSW** on `chapters.embedding` and `knowledge_nodes.embedding`; pg_trgm GIN on `knowledge_nodes.name`
- **source_ref bidirectional trace**: Every script element carries `{chapter_id, offset}`, 3-tier fallback (exact→prefix→estimated)
- **Application-layer retry**: Exponential backoff with jitter for all LLM calls (per-stage config, `LLM_MAX_RETRIES` env var)
- **UTF-8 everywhere**: stdin/stdout reconfigured on Windows, logging encoding, file upload encoding fallback (GB18030/GBK/GB2312/Big5)
- **Engine pool disposal**: `atexit` + FastAPI lifespan + test fixture teardown (3-layer guarantee)
- **Auth middleware**: `get_current_user` enforces Bearer JWT on all write endpoints; `require_ownership()` helper for resource-level access control

### Database Tables

| Table | Purpose |
|-------|---------|
| `users` | Accounts (argon2, JWT, admin seed) |
| `novels` | Uploaded novels with source_text |
| `chapters` | Pre-split chapters (preferred over re-chunking) |
| `tasks` | Script conversion jobs (status machine: pending→preprocessing→converting→completed/failed) |
| `knowledge_nodes` | KG nodes (character/location/item/event/organization) |
| `knowledge_edges` | KG edges with relation + weight |
| `operations` | Editor operation history (JSON Patch + undo) |
| `dialogues` | AI chat conversation threads |
| `audit_logs` | System audit trail (status transitions etc.) |

### Task State Machine

```
pending → preprocessing → converting → completed
    │          │              │
    └──────────┴──────────────┴──→ failed ──→ converting (resume)
```

## Key Design Principles

- **Pydantic V2 strict validation everywhere**: Every LLM output must pass a Pydantic model before entering the system
- **Source anchoring**: Every script element carries `source_ref` with `chapter_id` + `offset` for bidirectional traceability
- **Paragraph-aligned slicing**: Input is split on `\n\n+` boundaries, short paragraphs merged — never mid-sentence
- **Model-aware context budgets**: Auto-detected from model name, .env overridable, conservative CJK ratio (0.6 chars/token)
- **Progressive degradation**: Each pipeline stage has a fallback — KG returns empty, converter returns [], optimizer keeps originals

## Competition Constraints (metadata.md)

This project participates in a judged competition. Important rules:
- Each PR must do exactly one thing; split large features into multiple small PRs
- PR descriptions must include: title summary, feature description, implementation approach, and testing method
- The `main` branch must remain runnable at all times — judges may check at any point
- All commits must fall within the competition window; no "last-day bulk import"
- When collaborating, each team member must use their own GitHub account for commits

## Related Documentation

- `docs/business-logic.md` — Full API reference with activity diagrams, data models, state machines (v2.1.0)
- `docs/SRS 需求规格说明书.md` — Software requirements specification
- `docs/SDS 软件设计说明书.md` — Software design specification
- `docs/YAML_Schema_设计说明.md` — YAML schema design rationale
- `docs/dev_references.md` — External documentation index
- `.temp/DEVELOPMENT_STATUS.md` — Frontend development status (files, routes, stores, hooks, tests)
- `.temp/novel_samples/` — Sample Chinese novel files for testing
