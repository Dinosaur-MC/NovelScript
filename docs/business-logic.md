# NovelScript Business Logic Documentation

> AI-driven novel-to-script conversion pipeline.
> Backed by an 8-table PostgreSQL All-in-One data layer.

**Version:** 2.0.0  
**Generated:** 2026-06-06

---

## Table of Contents

1. [System Architecture](#1-system-architecture)
2. [Data Models](#2-data-models)
3. [API Reference](#3-api-reference)
4. [Pipeline Engine](#4-pipeline-engine)
5. [State Machines](#5-state-machines)
6. [Service Layer](#6-service-layer)
7. [SSE Progress Streaming](#7-sse-progress-streaming)

---

## 1. System Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     Frontend (React 19)                  │
│   Three-panel IDE: Reader | YAML Editor | Knowledge Graph │
└──────────────────────┬──────────────────────────────────┘
                       │ REST + SSE
┌──────────────────────▼──────────────────────────────────┐
│                  FastAPI Backend (Sync)                   │
│                                                          │
│  /api/v1/auth/*      User auth (JWT + argon2)            │
│  /api/v1/novels/*    Novel upload & management            │
│  /api/v1/tasks/*     Task lifecycle + SSE streaming       │
│  /api/v1/scripts/*   Script CRUD + export                │
│  /api/v1/editor/*    AI chat + JSON Patch editing         │
│                                                          │
│  Services:                                               │
│    BaseCRUD          Generic repository                   │
│    ProgressManager   Thread-safe SSE event dispatcher     │
│    Pipeline Executor Background daemon thread             │
└──────────────────────┬──────────────────────────────────┘
                       │ psycopg2 (sync)
┌──────────────────────▼──────────────────────────────────┐
│              PostgreSQL 18 (All-in-One)                   │
│                                                          │
│  8 tables: users, novels, tasks, chapters,                │
│            knowledge_nodes, knowledge_edges,              │
│            operations, dialogues, audit_logs              │
│                                                          │
│  Extensions: pgvector (HNSW), uuid-ossp, pg_trgm          │
└─────────────────────────────────────────────────────────┘
```

---

## 2. Data Models

### 2.1 Entity Relationship Diagram

```
users ──┐
        ├── novels ──┬── chapters
        │            ├── tasks ──┬── knowledge_nodes ──┐
        │            │           ├── operations        │
        │            │           ├── dialogues         │
        │            │           └── audit_logs         │
        │            │                                 │
        │            └── knowledge_nodes ───────────────┘
        │                 knowledge_edges (FKs to knowledge_nodes)
        │
        └── (tasks, operations, dialogues, audit_logs)
            have optional user_id FKs
```

### 2.2 users

| Column | Type | Default | Constraints |
|--------|------|---------|-------------|
| `id` | UUID (PK) | `uuid4()` | |
| `username` | VARCHAR(150) | | UNIQUE |
| `email` | VARCHAR(320) | | UNIQUE |
| `password_hash` | VARCHAR(255) | | |
| `display_name` | VARCHAR(200) | NULL | |
| `avatar_url` | TEXT | NULL | |
| `role` | VARCHAR(10) | `'user'` | CHECK IN ('admin','user') |
| `is_active` | BOOLEAN | `true` | |
| `last_login_at` | TIMESTAMPTZ | NULL | |
| `created_at` | TIMESTAMPTZ | `now()` | |
| `updated_at` | TIMESTAMPTZ | `now()` | |

### 2.3 novels

| Column | Type | Default | Constraints |
|--------|------|---------|-------------|
| `id` | UUID (PK) | `uuid4()` | |
| `user_id` | UUID (FK→users.id) | NULL | ON DELETE SET NULL |
| `title` | VARCHAR(500) | | NOT NULL |
| `author` | VARCHAR(300) | NULL | |
| `source_text` | TEXT | NULL | Full raw novel text |
| `word_count` | INTEGER | 0 | |
| `language` | VARCHAR(5) | `'zh'` | CHECK IN ('zh','en') |
| `status` | VARCHAR(20) | `'draft'` | CHECK IN ('draft','processing','completed') |
| `metadata` | JSONB | `'{}'` | |
| `created_at` | TIMESTAMPTZ | `now()` | |
| `updated_at` | TIMESTAMPTZ | `now()` | |

### 2.4 tasks

| Column | Type | Default | Constraints |
|--------|------|---------|-------------|
| `id` | UUID (PK) | `uuid4()` | |
| `novel_id` | UUID (FK→novels.id) | | NOT NULL, ON DELETE CASCADE |
| `user_id` | UUID (FK→users.id) | NULL | ON DELETE SET NULL |
| `status` | VARCHAR(30) | `'pending'` | CHECK IN ('pending','preprocessing','converting','completed','failed') |
| `progress` | INTEGER | 0 | CHECK 0–100 |
| `summary` | TEXT | NULL | One-paragraph script summary |
| `characters_json` | JSONB | `'[]'` | Array of character objects |
| `script_yaml` | TEXT | NULL | Full script in YAML format |
| `script_json` | JSONB | NULL | Full script as nested dict |
| `script_fountain` | TEXT | NULL | Fountain format (future) |
| `error_message` | TEXT | NULL | Pipeline failure details |
| `pipeline_config` | JSONB | `'{}'` | Configuration overrides |
| `created_at` | TIMESTAMPTZ | `now()` | |
| `updated_at` | TIMESTAMPTZ | `now()` | |

### 2.5 chapters

| Column | Type | Default | Constraints |
|--------|------|---------|-------------|
| `id` | UUID (PK) | `uuid4()` | |
| `novel_id` | UUID (FK→novels.id) | | NOT NULL, ON DELETE CASCADE |
| `chapter_index` | INTEGER | | NOT NULL |
| `title` | VARCHAR(500) | NULL | |
| `content` | TEXT | NULL | Chapter body text |
| `embedding` | VECTOR(1536) | NULL | pgvector HNSW index |
| `metadata` | JSONB | `'{}'` | |
| `created_at` | TIMESTAMPTZ | `now()` | |

Unique index: `uq_chapters_novel_index` ON `(novel_id, chapter_index)`.

### 2.6 knowledge_nodes

| Column | Type | Default | Constraints |
|--------|------|---------|-------------|
| `id` | UUID (PK) | `uuid4()` | |
| `novel_id` | UUID (FK→novels.id) | | NOT NULL, ON DELETE CASCADE |
| `task_id` | UUID (FK→tasks.id) | NULL | ON DELETE SET NULL |
| `node_type` | VARCHAR(20) | | CHECK IN ('character','location','item','organization','event','concept') |
| `name` | VARCHAR(300) | | NOT NULL |
| `aliases` | TEXT[] | `'{}'` | |
| `description` | TEXT | NULL | |
| `properties` | JSONB | `'{}'` | Extensible metadata |
| `embedding` | VECTOR(1536) | NULL | pgvector HNSW index |
| `created_at` | TIMESTAMPTZ | `now()` | |
| `updated_at` | TIMESTAMPTZ | `now()` | |

pg_trgm GIN index on `name` for fuzzy search.

### 2.7 knowledge_edges

| Column | Type | Default | Constraints |
|--------|------|---------|-------------|
| `id` | UUID (PK) | `uuid4()` | |
| `novel_id` | UUID (FK→novels.id) | | NOT NULL, ON DELETE CASCADE |
| `task_id` | UUID (FK→tasks.id) | NULL | ON DELETE SET NULL |
| `source_node_id` | UUID (FK→knowledge_nodes.id) | | ON DELETE CASCADE |
| `target_node_id` | UUID (FK→knowledge_nodes.id) | | ON DELETE CASCADE |
| `relation` | VARCHAR(100) | `''` | e.g. 'friend_of', 'located_in' |
| `weight` | FLOAT | 1.0 | Confidence 0.0–1.0 |
| `evidence` | TEXT | NULL | Source text citation |
| `metadata` | JSONB | `'{}'` | |
| `created_at` | TIMESTAMPTZ | `now()` | |

### 2.8 operations

| Column | Type | Default | Constraints |
|--------|------|---------|-------------|
| `id` | UUID (PK) | `uuid4()` | |
| `task_id` | UUID (FK→tasks.id) | | ON DELETE CASCADE |
| `user_id` | UUID (FK→users.id) | NULL | ON DELETE SET NULL |
| `type` | VARCHAR(20) | | CHECK IN ('manual_edit','ai_patch','snapshot','rollback') |
| `target_path` | TEXT | NULL | JSON Pointer path |
| `diff_json` | JSONB | `'{}'` | The applied change |
| `previous_snapshot` | JSONB | NULL | Value before change (for undo) |
| `applied` | BOOLEAN | `true` | Whether this op is currently active |
| `created_at` | TIMESTAMPTZ | `now()` | |

### 2.9 dialogues

| Column | Type | Default | Constraints |
|--------|------|---------|-------------|
| `id` | UUID (PK) | `uuid4()` | |
| `task_id` | UUID (FK→tasks.id) | | ON DELETE CASCADE |
| `user_id` | UUID (FK→users.id) | NULL | ON DELETE SET NULL |
| `role` | VARCHAR(10) | | CHECK IN ('user','assistant','system') |
| `content` | TEXT | `''` | Chat message body |
| `patch_json` | JSONB | `'{}'` | JSON Patch extracted from message |
| `metadata` | JSONB | `'{}'` | Context metadata |
| `created_at` | TIMESTAMPTZ | `now()` | |

### 2.10 audit_logs

| Column | Type | Default | Constraints |
|--------|------|---------|-------------|
| `id` | UUID (PK) | `uuid4()` | |
| `user_id` | UUID (FK→users.id) | NULL | ON DELETE SET NULL |
| `task_id` | UUID (FK→tasks.id) | NULL | ON DELETE SET NULL |
| `level` | VARCHAR(10) | `'info'` | CHECK IN ('debug','info','warn','error','fatal') |
| `category` | VARCHAR(100) | NULL | e.g. 'task_status' |
| `message` | TEXT | `''` | Human-readable description |
| `detail` | JSONB | `'{}'` | Structured data (from→to states) |
| `created_at` | TIMESTAMPTZ | `now()` | |

---

## 3. API Reference

All responses use `BaseResponse(code, message, data)` wrapper unless noted.

### 3.1 Auth — `/api/v1/auth`

#### POST /register

```
Request:  { username: str, email: str, password: str }
Response: { user_id: UUID, username: str }
Errors:   409 (duplicate email/username)
```

```
┌──────┐    ┌──────────────────┐    ┌──────────┐
│Client│    │    /auth/register │    │   users  │
└──┬───┘    └────────┬─────────┘    └────┬─────┘
   │  POST /register  │                  │
   │─────────────────►│                  │
   │                  │ SELECT by email  │
   │                  │─────────────────►│
   │                  │◄─────(row?)──────│
   │                  │                  │
   │                  │ [if exists] 409  │
   │                  │                  │
   │                  │ hash(password)   │
   │                  │ INSERT user      │
   │                  │─────────────────►│
   │                  │◄─────(ok)────────│
   │◄──── 200 ────────│                  │
```

#### POST /login

```
Request:  { email: str, password: str }
Response: { token: JWT, user: { id, username, role } }
Errors:   401
```

```
┌──────┐    ┌──────────────┐    ┌──────────┐    ┌───────┐
│Client│    │  /auth/login  │    │   users  │    │  JWT  │
└──┬───┘    └──────┬───────┘    └────┬─────┘    └───┬───┘
   │  POST /login   │                │              │
   │───────────────►│                │              │
   │                │ SELECT by email│              │
   │                │───────────────►│              │
   │                │◄────(user)─────│              │
   │                │ verify_pw()    │              │
   │                │ [mismatch] 401 │              │
   │                │                │              │
   │                │ UPDATE last_login_at          │
   │                │──────────────────────────────►│
   │                │ create_access_token(user_id)  │
   │                │◄────────────(jwt)─────────────│
   │◄── 200 + jwt ──│                               │
```

#### GET /me

```
Headers:  Authorization: Bearer <jwt>
Response: { id, username, email, role }
Errors:   401
```

#### POST /logout

```
Response: { message: "已登出" }
Note:     Stub — no token invalidation (JWT stateless).
```

### 3.2 Novels — `/api/v1/novels`

#### POST /upload

```
Request:  { content: str (≤5MB), title?: str, author?: str }
Response: { novel_id: UUID, title: str, chapters: [{index, title}] }
Errors:   400 (empty), 413 (too large)
```

```
┌──────┐    ┌─────────────────┐    ┌───────────┐    ┌──────────┐
│Client│    │  /novels/upload  │    │  cli.chunker│    │ novels   │
└──┬───┘    └───────┬─────────┘    └─────┬─────┘    │ chapters │
   │  POST /upload   │                   │          └────┬─────┘
   │────────────────►│                   │               │
   │                 │ validate size     │               │
   │                 │ split_chapters()  │               │
   │                 │──────────────────►│               │
   │                 │◄─ list[Chapter] ──│               │
   │                 │                   │               │
   │                 │ INSERT novel      │               │
   │                 │──────────────────────────────────►│
   │                 │                   │               │
   │                 │ [for each ch] INSERT chapter      │
   │                 │──────────────────────────────────►│
   │◄──── 200 ───────│                                    │
```

#### POST /upload/file

```
Multipart: file (text/plain), title (form), author (form?)
Same flow as /upload after reading file.
```

#### GET /

```
Query:    page: int=1, limit: int=20
Response: { total, items: [novel] }
```

#### GET /{novel_id}

```
Response: { novel, chapters: [chapter] }
Errors:   404, 422 (invalid UUID)
```

#### PUT /{novel_id}

```
Request:  { title?: str, author?: str }
Response: { novel }
Errors:   400 (nothing to update), 404, 422
```

#### DELETE /{novel_id}

```
Response: { deleted_id: UUID }
Errors:   404, 422
Flow:     DELETE chapters WHERE novel_id → DELETE novel
```

### 3.3 Tasks — `/api/v1/tasks`

#### POST /

```
Request:  { novel_id: str (UUID), pipeline_config?: dict }
Response: { task_id: UUID, status: "pending" }
Errors:   400 (invalid UUID), 404 (novel not found)
Side effect: Spawns background daemon thread running pipeline
```

```
┌──────┐    ┌──────────────┐    ┌──────────┐    ┌──────────────────┐
│Client│    │  /tasks/ POST │    │   tasks  │    │ pipeline_executor│
└──┬───┘    └──────┬───────┘    └────┬─────┘    └────────┬─────────┘
   │  POST /tasks   │                │                    │
   │───────────────►│                │                    │
   │                │ validate novel │                    │
   │                │ INSERT task    │                    │
   │                │───────────────►│                    │
   │                │◄────(ok)───────│                    │
   │                │ commit()       │                    │
   │                │                │                    │
   │                │ execute_pipeline(task_id, novel_id) │
   │                │────────────────────────────────────►│
   │                │                │  spawn daemon      │
   │                │                │  thread            │
   │◄──── 200 ──────│                │                    │
   │                │                │                    │
   │    SSE stream via GET /stream   │                    │
   │◄════════════════════════════════════════════════════►│
```

#### GET /

```
Query:    novel_id?: UUID, status?: str, page: int=1, limit: int=20
Response: { tasks: [{id, novel_id, status, progress, summary, error_message, created_at, updated_at}], total, page, limit }
```

#### GET /{task_id}/stream (SSE)

```
Response: text/event-stream
Events:   progress { progress: int, stage: str }
          complete { progress: 100 }
          error    { error: str }
          heartbeat (empty, every 0.5s)
Errors:   400, 404
```

```
┌──────────┐    ┌──────────────────┐    ┌─────────────────┐
│  Client  │    │ GET /{id}/stream │    │ ProgressManager │
└────┬─────┘    └────────┬─────────┘    └────────┬────────┘
     │ GET /stream        │                       │
     │───────────────────►│                       │
     │                    │ create_queue(task_id) │
     │                    │──────────────────────►│
     │                    │◄─────(queue)──────────│
     │                    │                       │
     │                    │ check task status     │
     │                    │ [if completed/failed] │
     │                    │ yield final event     │
     │◄── event ──────────│                       │
     │                    │                       │
     │                    │  ┌── poll loop ──┐    │
     │                    │  │ get_nowait()  │    │
     │                    │  │───────────────────►│
     │                    │  │◄──(event/None)────│──── background thread pushes
     │                    │  │ yield SSE event   │
     │◄══ event ═════════│  │                │    │
     │                    │  │ sleep(0.5)    │    │
     │                    │  └───────────────┘    │
     │                    │                       │
     │                    │ [disconnect]          │
     │                    │ remove_queue(task_id) │
     │                    │──────────────────────►│
```

#### GET /{task_id}/status

```
Response: { task_id, status, progress, error_message }
Note:     Lightweight — no script artifacts.
```

#### PUT /{task_id}/status

```
Request:  { status: str, progress?: int (0–100), error_message?: str }
Response: { task_id, status, progress, error_message }
Errors:   400, 404, 422 (invalid transition)
Side effect: Writes AuditLog on status change
```

#### POST /{task_id}/resume

```
Response: { task_id, status: "converting" }
Errors:   400, 404, 422 (task not in "failed")
Side effect: Re-spawns pipeline background thread
```

```
┌──────┐    ┌───────────────┐    ┌──────────┐    ┌──────────────────┐
│Client│    │   /resume     │    │   tasks  │    │ pipeline_executor│
└──┬───┘    └──────┬────────┘    └────┬─────┘    └────────┬─────────┘
   │ POST /resume   │                │                    │
   │───────────────►│                │                    │
   │                │ [status≠failed] 422                 │
   │                │                │                    │
   │                │ SET converting │                    │
   │                │ CLEAR error_msg│                    │
   │                │───────────────►│                    │
   │                │ AuditLog       │                    │
   │                │ commit()       │                    │
   │                │                │                    │
   │                │ execute_pipeline(task_id, novel_id) │
   │                │────────────────────────────────────►│
   │◄──── 200 ──────│                                     │
```

#### GET /{task_id}

```
Response: Full task detail including all script artifacts
Note:     Must be registered LAST after /stream, /status
```

### 3.4 Scripts — `/api/v1/scripts`

> Scripts are stored in the `tasks` table. `script_id` maps to `Task.id`.

#### GET /

```
Query:    novel_id?: UUID, status?: str, page: int=1, limit: int=20
Response: { items: [{script_id, novel_id, status, progress, summary, scene_count, created_at, updated_at}], total, page, limit }
```

#### GET /{script_id}

```
Response: { script_id, novel_id, status, progress, summary, script_yaml, script_json, script_fountain, characters_json, created_at, updated_at }
Errors:   404, 422
```

#### PUT /{script_id}

```
Request:  { script_yaml: str }
Response: { script_id, updated_at, validation: { valid: bool, errors: str? } }
Errors:   404, 422 (invalid YAML)
Side effect: Creates Operation row (type="manual_edit", target_path="/script_yaml")
```

```
┌──────┐    ┌───────────────┐    ┌──────────┐    ┌────────────┐
│Client│    │ PUT /{script_id}│   │   tasks  │    │ operations │
└──┬───┘    └──────┬────────┘    └────┬─────┘    └─────┬──────┘
   │ PUT /{id}      │                │                 │
   │───────────────►│                │                 │
   │                │ yaml.safe_load()                 │
   │                │ [invalid] 422  │                 │
   │                │                │                 │
   │                │ SET script_yaml│                 │
   │                │ UPDATE tasks   │                 │
   │                │───────────────►│                 │
   │                │                │                 │
   │                │ INSERT Operation (manual_edit)   │
   │                │─────────────────────────────────►│
   │◄──── 200 ──────│                                  │
```

#### DELETE /{script_id}

```
Response: { script_id }
Note:     Deletes the Task row (cascades to operations, dialogues, audit_logs)
```

#### GET /{script_id}/export

```
Query:    format: "yaml"|"json"|"fountain" (default: yaml)
Response: PlainTextResponse with raw content
Errors:   404, 422
```

### 3.5 Editor — `/api/v1/editor`

#### POST /chat/{task_id}

```
Request:  { message: str (min_length=1), scene_id?: str }
Response: { reply: str, patch: dict? }
Errors:   400, 404, 503 (LLM unavailable)
```

```
┌──────┐    ┌───────────────┐    ┌──────────┐    ┌───────────┐    ┌───────┐
│Client│    │ /chat/{task_id}│   │  tasks   │    │ dialogues │    │  LLM  │
└──┬───┘    └──────┬────────┘    └────┬─────┘    └─────┬─────┘    └──┬────┘
   │ POST /chat     │                │                 │             │
   │───────────────►│                │                 │             │
   │                │ GET task       │                 │             │
   │                │───────────────►│                 │             │
   │                │◄──(row)────────│                 │             │
   │                │                │                 │             │
   │                │ _build_chat_messages(task, msg)  │             │
   │                │ llm.invoke(messages)             │             │
   │                │───────────────────────────────────────────────►│
   │                │◄──────────────(reply)─────────────────────────│
   │                │                │                 │             │
   │                │ INSERT user dialogue            │             │
   │                │────────────────────────────────►│             │
   │                │ INSERT assistant dialogue       │             │
   │                │────────────────────────────────►│             │
   │                │                │                 │             │
   │                │ _extract_json_patch(reply)      │             │
   │                │ [if found] UPDATE dialogue.patch_json          │
   │                │────────────────────────────────►│             │
   │◄──── 200 ──────│                                  │             │
```

#### POST /apply_patch/{task_id}

```
Request:  { op: "add"|"replace"|"remove", path: str, value: any }
Response: { script_json, operation_id: UUID }
Errors:   400, 404
```

```
┌──────┐    ┌────────────────────┐    ┌──────────┐    ┌────────────┐
│Client│    │ /apply_patch/{id}   │    │  tasks   │    │ operations │
└──┬───┘    └─────────┬──────────┘    └────┬─────┘    └─────┬──────┘
   │ POST /apply_patch │                   │                 │
   │──────────────────►│                   │                 │
   │                   │ GET task          │                 │
   │                   │──────────────────►│                 │
   │                   │◄──(row)───────────│                 │
   │                   │                   │                 │
   │                   │ _get_at_path(script_json, path)     │
   │                   │ (capture for undo) │                 │
   │                   │                   │                 │
   │                   │ _apply_patch_op() │                 │
   │                   │ (RFC 6901 pointer)│                 │
   │                   │ flag_modified(task, "script_json")   │
   │                   │ UPDATE tasks      │                 │
   │                   │──────────────────►│                 │
   │                   │                   │                 │
   │                   │ INSERT Operation (ai_patch)          │
   │                   │─────────────────────────────────────►│
   │◄──── 200 ─────────│                                      │
```

#### POST /undo/{task_id}

```
Response: { script_json, undone_operation_id, rollback_operation_id }
Errors:   400 (nothing to undo), 404
```

```
┌──────┐    ┌───────────────┐    ┌──────────┐    ┌────────────┐
│Client│    │ /undo/{id}    │    │  tasks   │    │ operations │
└──┬───┘    └──────┬────────┘    └────┬─────┘    └─────┬──────┘
   │ POST /undo     │                │                 │
   │───────────────►│                │                 │
   │                │ GET last non-rollback op         │
   │                │─────────────────────────────────►│
   │                │◄──(op)───────────────────────────│
   │                │ [none found] 400 │                 │
   │                │                │                 │
   │                │ compute inverse patch            │
   │                │ apply inverse    │                 │
   │                │ UPDATE tasks    │                 │
   │                │───────────────►│                 │
   │                │                │                 │
   │                │ SET op.applied = False           │
   │                │─────────────────────────────────►│
   │                │ INSERT rollback Operation        │
   │                │─────────────────────────────────►│
   │◄──── 200 ──────│                                  │
```

---

## 4. Pipeline Engine

### 4.1 Stage Sequence

```
Raw Text → Stage1:Chunking → Stage2:GraphRAG → Stage3:RAG → Stage4:Conversion → Stage5:Optimization → Stage6:Assembly → Script
```

```
     0%             10%            25%           35%            35-80%               95%              100%
     │               │              │             │               │                   │                 │
  starting       chunking       graphrag        rag         converting          optimizing        assembling
```

| Stage | Model | Function | Progress |
|-------|-------|----------|----------|
| 0. Loading | — | `Path.read_text()` or in-memory | 0% |
| 1. Chunking | DeepSeek Flash (fallback) | `split_chapters()` regex → LLM | 10% |
| 2. GraphRAG | DeepSeek Pro | `extract_graph()` JSON mode | 25% |
| 3. RAG Index | OpenRouter `text-embedding-3-small` | `build_index()` FAISS | 35% |
| 4. Conversion | DeepSeek Flash (parallel per chapter) | `convert_chapter()` | 35–80% |
| 5. Optimization | DeepSeek Pro | `optimize()` cross-scene check | 95% |
| 6. Assembly | — | Build `Script` model | 100% |

### 4.2 Data Flow

```
Novel.source_text
        │
        ▼
split_chapters(text)
        │
        ▼
list[Chapter] ──┬── extract_graph() ──► KnowledgeGraph (35 nodes, 60 edges typical)
                │
                └── build_index() ────► FAISS index (in-memory)
                        │
                        ▼
              [per chapter, parallel]
              search(faiss, ch.text[:500]) → rag_ctx
              convert_chapter(ch, kg, rag_ctx) → list[Scene]
                        │
                        ▼
              list[Scene] (all chapters merged)
                        │
                        ▼
              optimize(all_scenes, kg)
              _restore_source_refs(original, optimized)  ← preserves tracing
                        │
                        ▼
              Script { meta, summary, characters, scenes, knowledge_graph }
                        │
                        ▼
              to_yaml() / to_json() → saved to Task.script_yaml / script_json
```

### 4.3 Graceful Degradation

| Stage | Failure behavior |
|-------|-----------------|
| Chunking (LLM) | Falls back to single-chapter wrapping |
| GraphRAG | Returns empty `KnowledgeGraph()` |
| RAG Index | Returns `None` → keyword fallback on chapter texts |
| Conversion | Returns `[]` for that chapter (others continue) |
| Optimization | Returns original unoptimized scenes |
| Assembly | Always succeeds |

### 4.4 Model Routing

| Pipeline Stage | LLM Model | Purpose |
|---------------|-----------|---------|
| `chapter_split` | `deepseek-v4-flash` | Regex fallback chapter detection |
| `global_extraction` | `deepseek-v4-pro` | Knowledge graph extraction |
| `scene_conversion` | `deepseek-v4-flash` | Per-chapter scene generation |
| `consistency_check` | `deepseek-v4-pro` | Cross-scene optimization |
| `ai_chat` | `deepseek-v4-flash` | Editor AI chat assistant |

---

## 5. State Machines

### 5.1 Task Status State Machine

```
                    ┌──────────┐
          ┌────────►│  failed  │◄─────────┐
          │         └────┬─────┘          │
          │              │    resume       │
          │         ┌────▼─────┐          │
          │         │converting│          │
          │         └────┬─────┘          │
          │              │                │
┌─────────┴──┐    ┌─────▼──────┐   ┌─────┴──────┐
│   pending   ├───►│preprocessing├──►│  completed │
└─────────────┘    └─────┬──────┘   └────────────┘
                         │                ▲
                         │                │
                         └──► failed ─────┘
```

**Valid transitions:**
```
pending       → preprocessing | converting | failed
preprocessing → converting | failed
converting    → completed | failed
failed        → converting
```

**Transition triggers:**
- `pending → preprocessing`: Pipeline starts, chunking/graphrag/rag stages
- `preprocessing → converting`: Pipeline enters scene conversion stage
- `converting → completed`: Pipeline finishes successfully
- Any → `failed`: Exception during execution or `PUT /status`
- `failed → converting`: `POST /resume` (re-spawns pipeline)

### 5.2 Novel Status

```
draft → processing → completed
```

Set by the application, not automatically transitioned.

### 5.3 Operation Lifecycle

```
               POST /apply_patch
                     │
               ┌─────▼──────┐
               │  applied=T │
               └─────┬──────┘
                     │ POST /undo
               ┌─────▼──────┐
               │  applied=F │    (cannot be undone again)
               └────────────┘
```

---

## 6. Service Layer

### 6.1 BaseCRUD[T]

Generic synchronous repository for all 8 tables.

```
create(db, obj)        → obj          (add, flush, refresh)
get(db, pk)            → obj | None   (session.get)
list(db, offset, limit, filters, order_by) → (rows, total)
update(db, pk, dict)   → obj | None   (set attrs, auto updated_at)
delete(db, pk)         → bool         (get, delete, flush)
```

### 6.2 ProgressManager

Thread-safe singleton bridging background pipeline threads ↔ SSE HTTP endpoint.

```
┌──────────────────────────────────────┐
│          ProgressManager             │
│                                      │
│  _queues: dict[str, queue.Queue]     │
│  _lock:   threading.Lock()           │
│                                      │
│  create_queue(task_id) → Queue       │
│  remove_queue(task_id)               │
│  push(task_id, type, data)           │
│  push_progress(task_id, pct, stage)  │
│  push_complete(task_id)              │
│  push_error(task_id, msg)            │
│  get_nowait(task_id) → dict|None     │
│  cleanup(task_id)                    │
└──────────────────────────────────────┘
         ▲                    │
         │ Push               │ Poll (non-blocking)
         │ (background        │ (async SSE generator)
         │  thread)           │
  ┌──────┴──────┐     ┌───────▼──────┐
  │ Pipeline    │     │ GET /stream  │
  │ Executor    │     │ (EventSource │
  │ Thread      │     │  Response)   │
  └─────────────┘     └──────────────┘
```

**Key safety properties:**
- `queue.Queue` is inherently thread-safe — no `asyncio` bridging needed
- `threading.Lock` guards the `_queues` dictionary
- Events pushed before an SSE client connects are silently dropped
- `cleanup()` is called by both the SSE generator (on disconnect) and the pipeline thread (on completion) — idempotent

### 6.3 Pipeline Executor

```
execute_pipeline(task_id, novel_id)
  │
  └─ spawn daemon thread
       │
       ├─ own DB session (_session_factory())
       ├─ load Novel.source_text
       ├─ [empty?] → log warning, return (task stays "pending")
       │
       ├─ progress callback closure:
       │    ├─ DB: update progress + status
       │    ├─ commit()
       │    └─ progress_manager.push_progress()
       │
       ├─ asyncio.run(run_from_text(text, callback))
       │
       ├─ on success:
       │    ├─ task.status = "completed"
       │    ├─ task.progress = 100
       │    ├─ task.summary = script.summary
       │    ├─ task.script_yaml = to_yaml(script)
       │    ├─ task.script_json = script.model_dump(mode="json")
       │    ├─ task.characters_json = [char dicts]
       │    ├─ commit()
       │    └─ progress_manager.push_complete()
       │
       ├─ on failure:
       │    ├─ task.status = "failed"
       │    ├─ task.error_message = traceback[:5000]
       │    ├─ commit()
       │    └─ progress_manager.push_error()
       │
       └─ finally:
            ├─ session.close()
            └─ progress_manager.cleanup()
```

**`recover_stale_tasks()`** — called at `init_db()` startup:
- Finds all tasks with `status IN ("preprocessing", "converting")`
- Sets them to `"failed"` with message: "Server restarted — pipeline interrupted"
- Users can resume via `POST /resume`

---

## 7. SSE Progress Streaming

### 7.1 Event Protocol

All events use the SSE wire format:
```
event: <type>
data: <json>
```

| Event | Data | Stream behavior |
|-------|------|----------------|
| `progress` | `{"progress": 35, "stage": "converting"}` | Continues |
| `complete` | `{"progress": 100}` | Closes |
| `error` | `{"error": "Traceback ..."}` | Closes |
| `heartbeat` | `""` | Keeps alive (every 0.5s) |

### 7.2 Connection Lifecycle

```
Client connects ──► GET /{task_id}/stream
                        │
                        ├─ [task already completed?] → yield "complete" → close
                        ├─ [task already failed?]    → yield "error"   → close
                        │
                        └─ [task in progress] → enter poll loop
                              │
                              ├─ get_nowait() → yield event
                              ├─ queue.Empty → sleep 0.5s → yield heartbeat
                              │
                              ├─ "complete" event → close
                              ├─ "error" event   → close
                              │
                              └─ [client disconnects] → finally: remove_queue()
```

### 7.3 Progress Values

| Progress | Stage | DB Status |
|----------|-------|-----------|
| 0% | starting | pending |
| 10% | chunking | preprocessing |
| 25% | graphrag | preprocessing |
| 35% | rag | preprocessing |
| 35–80% | converting | converting |
| 95% | optimizing | converting |
| 100% | assembling | completed |
```

---

## Appendix: Complete Route Table

| Method | Path | Purpose | Auth |
|--------|------|---------|------|
| POST | `/api/v1/auth/register` | Create account | No |
| POST | `/api/v1/auth/login` | Login → JWT | No |
| POST | `/api/v1/auth/logout` | Logout (stub) | No |
| GET | `/api/v1/auth/me` | Current user | Bearer |
| POST | `/api/v1/novels/upload` | Upload novel JSON | No |
| POST | `/api/v1/novels/upload/file` | Upload novel file | No |
| GET | `/api/v1/novels/` | List novels | No |
| GET | `/api/v1/novels/{id}` | Get novel + chapters | No |
| PUT | `/api/v1/novels/{id}` | Update novel | No |
| DELETE | `/api/v1/novels/{id}` | Delete novel + chapters | No |
| POST | `/api/v1/tasks/` | Create task + run pipeline | No |
| GET | `/api/v1/tasks/` | List tasks | No |
| GET | `/api/v1/tasks/{id}/stream` | SSE progress stream | No |
| GET | `/api/v1/tasks/{id}/status` | Task status | No |
| PUT | `/api/v1/tasks/{id}/status` | Update task status | No |
| POST | `/api/v1/tasks/{id}/resume` | Resume failed task | No |
| GET | `/api/v1/tasks/{id}` | Full task detail | No |
| GET | `/api/v1/scripts/` | List scripts | No |
| GET | `/api/v1/scripts/{id}` | Get script detail | No |
| PUT | `/api/v1/scripts/{id}` | Edit script YAML | No |
| DELETE | `/api/v1/scripts/{id}` | Delete script | No |
| GET | `/api/v1/scripts/{id}/export` | Export (yaml/json/fountain) | No |
| POST | `/api/v1/editor/chat/{id}` | AI chat | No |
| POST | `/api/v1/editor/apply_patch/{id}` | Apply JSON Patch | No |
| POST | `/api/v1/editor/undo/{id}` | Undo last patch | No |
| GET | `/health` | Health check | No |
