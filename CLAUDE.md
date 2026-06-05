# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

NovelScript (析幕) is an AI-driven pipeline that converts long-form novels (3+ chapters) into structured scripts compliant with film industry standards (Fountain 1.1 / YAML). The system emphasizes **deterministic pipelines over probabilistic LLM outputs** — strict validation, bidirectional source tracing, and an All-in-One PostgreSQL data layer anchor the AI's creativity.

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
uv sync                                    # Install dependencies
uv run main.py                             # Start dev server (uvicorn, port 8000, reload on DEBUG)
uv run pytest                              # Run tests
uv add <package>                           # Add a dependency
```

### Frontend (React 19 + React Router 7, Node 24)

```bash
cd frontend
pnpm install                               # Install dependencies
pnpm run dev                               # Start dev server (Vite HMR, port 5173)
pnpm run build                             # Production build (SSR)
pnpm run start                             # Serve production build
pnpm run typecheck                         # TypeScript type checking
```

## Architecture

### Backend (`backend/app/`)

```
app/
├── main.py          # FastAPI app factory — CORS, exception handlers, route registration
├── api/             # Per-version route modules (v1.py → /api/v1/*)
├── core/            # Config, security, DB connection (asyncpg)
├── models/          # Pydantic V2 schemas — BaseResponse/ErrorResponse, YAML script schema
├── services/        # Core business logic: LLM router, RAG retrieval, Auto-Fix loop
└── db/              # PostgreSQL DDL and init scripts
```

**Entry point**: `backend/main.py` loads `.env` via `python-dotenv`, then starts uvicorn against `app.main:app`.

**Key architectural patterns**:
- **Dual-model routing**: `DeepSeek-v4-pro` handles complex scene conversion and knowledge graph extraction; `DeepSeek-v4-flash` handles lightweight summaries, dialogue, and patch generation. Both gated behind `asyncio.Semaphore` for concurrency control.
- **Auto-Fix loop**: When LLM outputs invalid JSON/YAML, the `ValidationError` is caught and fed back to the LLM for correction (max 2 retries). This ensures 100% schema-compliant output.
- **SSE progress streaming**: Long-running pipeline jobs push progress events via `sse-starlette`.
- **All-in-One DB**: PostgreSQL 18 with `pgvector` (HNSW + KNN for RAG), `JSONB`/`JSONPath` (knowledge graph, script storage), and relational tables (tasks, operations) — no separate vector DB or graph DB.

### Frontend (`frontend/app/`)

```
app/
├── root.tsx          # Root layout (Inter font, ErrorBoundary)
├── routes.ts         # Route config → single index route at routes/home.tsx
├── routes/home.tsx   # Home page (currently renders Welcome component)
├── welcome/          # Placeholder welcome screen
└── app.css           # Tailwind CSS v4 import + Inter font theme
```

**Key architectural patterns**:
- **React Router 7 with SSR**: Server-side rendering enabled, using future v8 flags.
- **Planned component layout** (per README): Three-panel IDE — TipTap novel reader (left), Monaco YAML editor (center), ReactFlow knowledge graph (right) — with bidirectional trace linking via `source_ref` offsets.
- **State management**: Zustand stores (planned per README structure).
- **UI library**: Ant Design 6 + Tailwind CSS 4.

### YAML Schema Design (4-Layer Architecture)

1. **Layer 0 — Fountain 1.1 100% isomorphism**: Round-trip fidelity between YAML and Fountain syntax (8 element types, title page, section/synopsis, boneyard).
2. **Layer 1 — Structural enhancement**: Decomposed `heading` fields (`int_ext`, `location`, `time`), `dialogue_block` logical aggregation, `source_ref` 3D traceability, explicit `character_extension` fields.
3. **Layer 2 — Narrative extension (`metadata`)**: Markers for flashbacks/flash-forwards, multi-timeline IDs, voice-over subtypes, stream-of-consciousness — covering what Fountain's minimal syntax cannot express for novel adaptation.
4. **Layer 3 — Rendering & delivery**: Fountain export for toolchain compatibility + direct PDF rendering for industry compliance.

### Data Layer Philosophy

The project explicitly rejects the `MySQL + FAISS + Neo4j` stack in favor of a single PostgreSQL instance:
- **pgvector** with HNSW index replaces standalone vector DBs for RAG embeddings.
- **JSONB** with JSONPath replaces graph databases for character relationship graphs.
- This ensures ACID transactions and reduces Docker orchestration to a single DB container.

## Key Design Principles

- **Pydantic V2 strict validation everywhere**: Every LLM output must pass a Pydantic model before entering the system. The Auto-Fix loop catches and repairs format drift.
- **Source anchoring**: Every script element (dialogue, action) carries a `source_ref` with `chapter_id` + `offset` for bidirectional traceability between output script and input novel.
- **Fountain as strategic bridge**: `.fountain` export is an intermediate interchange format, not the final deliverable. The YAML Schema is the source of truth; Fountain export enables import into Final Draft, Celtx, etc.
- **Structured fallback**: Every structured field retains both the raw text and parsed sub-fields — if parsing fails, the system degrades gracefully to the raw text.

## Competition Constraints (metadata.md)

This project participates in a judged competition. Important rules:
- Each PR must do exactly one thing; split large features into multiple small PRs.
- PR descriptions must include: title summary, feature description, implementation approach, and testing method.
- The `main` branch must remain runnable at all times — judges may check at any point.
- All commits must fall within the competition window; no "last-day bulk import."
- When collaborating, each team member must use their own GitHub account for commits.
