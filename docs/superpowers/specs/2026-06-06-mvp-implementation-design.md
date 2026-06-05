# MVP Implementation Design

**Date:** 2026-06-06
**Source:** SDS v2.0.0 · SRS v2.3.0
**Scope:** 竖切 MVP — 端到端核心链路打通，纯命令行可测试

## 1. Strategy

Two-wave parallel execution. Each agent works in a git worktree, files independent PRs.

### Wave 1 (parallel)

| Agent | Title | Deliverables | Deps |
|-------|-------|-------------|------|
| A | Pipeline Engine | Chunking → RAG → GraphRAG → Conversion → YAML export. CLI testable, no DB | None |
| B | Database Foundation | DDL (8 tables), SQLModel mapping, pgvector/asyncpg driver setup, generic CRUD base, security layer | None |

### Wave 2 (parallel, triggered after B merges)

| Agent | Title | Deliverables | Deps |
|-------|-------|-------------|------|
| C | User System | `/api/auth/*` endpoints, JWT session, password hashing, middleware | B |
| D | Novel Management | `/api/novel/upload`, `/api/novel/preprocess/*`, novel CRUD, chapter storage | B |
| E | Script Management | `/api/scripts/*` CRUD, YAML/JSON/Fountain export, version diff | B |
| F | Task Management | `/api/tasks/*` — task lifecycle & state machine only; delegates execution to D/E/G | B |
| G | AI Chat | `/api/editor/*` endpoints, context-aware prompt assembly, JSON Patch generation | B |

## 2. Agent A — Pipeline Engine (no DB)

### Architecture
```
backend/cli/
├── pipeline.py         # Entry: python -m cli.pipeline <input_file>
├── chunker.py          # Regex + LLM fallback chapter splitting
├── rag_builder.py      # In-memory FAISS index (no pgvector yet)
├── graphrag_builder.py # Entity/relation extraction → dict graph
├── converter.py        # Stage 2: scene generation (Flash model)
├── optimizer.py        # Stage 3: consistency check (Pro model)
└── exporter.py         # JSON → YAML serialization
```

### Data Flow (CLI)
```
1. Read .txt → chunker.split() → List[Chapter]
2. Pro model: chapters → summary + characters + graph (in-memory dict)
3. Embedding (OpenRouter): chapters → in-memory FAISS index
4. Per chapter: Flash model(knowledge_graph + top-K RAG context) → Scene[]
5. Pro model: Scene[] → consistency check + optimization
6. exporter.to_yaml(script) → stdout / file
```

### Key Design Decisions
- **No DB** — everything in-memory. Knowledge graph is a dict. RAG is FAISS in memory.
- **Model router** — static routing table (Pro for Stage 1+3, Flash for Stage 2)
- **Embedding via OpenRouter** — `https://openrouter.ai/api/v1/embeddings` (OpenAI-compatible API), env: `OPENROUTER_API_KEY` + `OPENROUTER_BASE_URL`
- **LLM via DeepSeek** — Chat Completions endpoint, env: `DEEPSEEK_API_KEY`
- **Auto-Fix** — Pydantic V2 validation failure → retry with error context (max 2x)
- **CLI-only** — `uv run python -m cli.pipeline sample.txt` outputs YAML to stdout

### Pydantic Models Required
- `Chapter(text, title, index)`
- `Scene(scene_id, heading, location, time_of_day, elements[], characters_present[])`
- `Element(type, content, source_ref)`
- `Character(id, name, aliases, properties)`
- `KnowledgeGraph(nodes[], edges[])`
- `Script(meta, summary, characters[], scenes[], knowledge_graph)`

### Test Cases

| ID      | 场景           | 操作                                      | 预期结果                                                                 |
|---------|----------------|------------------------------------------|--------------------------------------------------------------------------|
| A-TC-01 | 正则章节切分   | `chunker.split("第一章\n...第二章\n...")`  | 返回 2 个 Chapter，索引正确，标题提取正确                                |
| A-TC-02 | LLM 兜底切分   | 输入无"第X章"标志的英文小说                | Flash 模型被调用做语义分章，返回 ≥1 个 Chapter                           |
| A-TC-03 | Stage 1 规划   | Pro 模型输入 3 章文本                      | 返回合法 `KnowledgeGraph`（≥3 个角色节点、≥2 条关系边）、`summary` 非空 |
| A-TC-04 | RAG 索引构建   | 3 章文本 → OpenRouter embedding → FAISS 索引 | 索引包含 3 个 vector(1536)，相似度查询返回正确的 top-1 章节             |
| A-TC-05 | Stage 2 转换   | Flash 模型 + KG context + RAG top-2        | 返回 Scene 列表，每个 Scene 含 heading + ≥1 Element，Pydantic 校验通过   |
| A-TC-06 | Auto-Fix 修复  | 注入非法 Element（缺少 type 字段）          | ≤2 次重试后修复成功；第 3 次仍非法时降级返回已解析部分 + 警告标记       |
| A-TC-07 | source_ref 注入 | Stage 2 输出后检查 Element                 | 每个 Element 的 `source_ref` 非空，`chapter_id` + `offset` 可追溯        |
| A-TC-08 | Stage 3 优化   | Pro 模型输入 3 个 Scene                    | 输出一致性问题标注（如有）或确认通过，结构未破坏                         |
| A-TC-09 | YAML 导出      | `exporter.to_yaml(script)`                 | 输出合法 YAML，含 meta/summary/characters/scenes/knowledge_graph 五段    |
| A-TC-10 | CLI 端到端     | `uv run python -m cli.pipeline sample.txt` | 退出码 0，stdout 输出完整 YAML，Pydantic 校验 100% 通过                  |

## 3. Agent B — Database Foundation

### Deliverables
```
backend/app/db/
├── init.sql                  # Full 8-table DDL from SDS §5.5
├── connection.py             # asyncpg pool factory (DATABASE_URL → pool)
└── migrations/               # Empty, reserved

backend/app/models/
├── sql.py                    # SQLModel classes for all 8 tables
└── patch.py                  # JSON Patch RFC 6902 model

backend/app/core/
├── config.py                 # pydantic-settings: DB_URL, API_KEY, DEBUG, MODEL_*
├── security.py               # password_hash(), verify_password(), create_token(), decode_token()
└── db.py                     # get_db() async generator, init_db()

backend/app/services/
└── base.py                   # Generic CRUD mixin (get, list, create, update, delete)
```

### SQLModel Classes (8 tables)
```python
class User(SQLModel, table=True)
class Novel(SQLModel, table=True)
class Task(SQLModel, table=True)
class Chapter(SQLModel, table=True)
class KnowledgeNode(SQLModel, table=True)
class KnowledgeEdge(SQLModel, table=True)
class Operation(SQLModel, table=True)
class Dialogue(SQLModel, table=True)
class AuditLog(SQLModel, table=True)
```

### Key Design Decisions
- `asyncpg` for raw DDL execution & pgvector queries (SQLModel doesn't have native vector support)
- `SQLModel` for ORM (CRUD + type safety)
- Connection pool via asyncpg, exposed to SQLModel via `create_async_engine`
- `security.py`: bcrypt/argon2 via passlib, JWT via pyjwt
- Generic CRUD: `class BaseCRUD[T]` with typed `get(id)`, `list(filters)`, `create(**kw)`, `update(id, **kw)`, `delete(id)`

### Test Cases

| ID      | 场景              | 操作                                             | 预期结果                                                      |
|---------|-------------------|-------------------------------------------------|---------------------------------------------------------------|
| B-TC-01 | DDL 建表          | `await init_db()`                                | 8 张表全部创建成功，无报错                                     |
| B-TC-02 | pgvector 扩展     | `SELECT extname FROM pg_extension`               | 返回 `vector` + `uuid-ossp` + `pg_trgm`                       |
| B-TC-03 | HNSW 索引         | `\d chapters`                                    | 索引存在，类型 HNSW，`vector_cosine_ops`                      |
| B-TC-04 | 外键约束          | 插入 `chapters` 使用无效 `novel_id`              | 抛出 `ForeignKeyViolationError`                                |
| B-TC-05 | CHECK 约束        | 插入 `knowledge_nodes` 使用无效 `node_type`      | 抛出 `CheckViolationError`                                    |
| B-TC-06 | SQLModel 读写     | `Novel.create(title="测试")` → `Novel.get(id)`   | 写入成功，读回数据一致                                         |
| B-TC-07 | 向量写入/检索     | 写入 embedding → KNN 查询                        | 返回 top-3 并按余弦距离排序                                    |
| B-TC-08 | 密码哈希          | `password_hash("test123")`                       | 输出 bcrypt/argon2 哈希串，`verify_password()` 验证通过        |
| B-TC-09 | JWT 令牌          | `create_token(user_id)` → `decode_token(token)`  | 解码成功，payload 含 `user_id`+`exp`；过期/伪造 token 解码失败 |
| B-TC-10 | Generic CRUD      | `BaseCRUD.get/list/create/update/delete`         | 五个方法全部通过，类型推断正确                                 |

## 4. Agent C–G — Business Modules (Wave 2)

Each agent builds one API module against the DB foundation:

| Agent | Route prefix | Key files | Unique challenge | Test Cases |
|-------|-------------|-----------|-----------------|------------|
| C | `/api/auth` | `api/auth.py`, `services/auth.py` | JWT middleware, session validation | C-TC-01: 注册 → 201 + user_id; C-TC-02: 重复邮箱 → 409; C-TC-03: 登录 → 200 + token; C-TC-04: 错误密码 → 401; C-TC-05: Bearer token `/me` → 200; C-TC-06: 无 token → 401 |
| D | `/api/novel` | `api/novel.py`, `services/novel.py` | Upload + chunking, novel-chapter FK | D-TC-01: 上传合法文本 → 200 + novel_id; D-TC-02: 空文本 → 400; D-TC-03: >5MB → 413; D-TC-04: 列表分页正确; D-TC-05: 单 novel 含 chapters 嵌套 |
| E | `/api/scripts` | `api/scripts.py`, `services/script.py` | YAML validation on save, version diff via operations table | E-TC-01: GET → 200 + 三格式; E-TC-02: PUT 非法 YAML → 422 + 错误位置; E-TC-03: PUT 合法 → 200 + operations 记录; E-TC-04: GET diff → patch 序列; E-TC-05: DELETE → 级联清理 |
| F | `/api/tasks` | `api/tasks.py`, `services/task.py`, `services/sse.py` | Task lifecycle & state machine only — delegates execution to D/E/G | F-TC-01: POST → 201 + pending; F-TC-02: pending→preprocessing→converting→completed 全流转; F-TC-03: 非法跳转 → 422; F-TC-04: SSE 收到 progress 事件; F-TC-05: resume 断点续传正确; F-TC-06: audit_log 事件写入 |
| G | `/api/editor` | `api/editor.py`, `services/chat.py` | Context assembly (scene + characters + source text) | G-TC-01: chat → 200 + reply; G-TC-02: 上下文注入含 scene 信息; G-TC-03: patch 生成合法; G-TC-04: apply_patch → script 更新 + operations 记录; G-TC-05: undo → 回退 + rollback 日志 |

## 5. What We Skip (MVP)

- Auth UI (login page)
- Monaco/TipTap/ReactFlow frontend components
- LangGraph orchestration (sequential calls suffice)
- pgvector HNSW (Agent A uses in-memory FAISS)
- knowledge_nodes/edges GraphRAG traversal (Agent A uses in-memory dict)
- Redis caching
- OAuth
- URL scraping
- TTS / Image generation
- Docker Compose / Nginx
- pg_cron log cleanup

## 6. Merge Order & Integration

```
Wave 1:
  main ← A (independent, merge first or anytime)
  main ← B (foundation for Wave 2)

Wave 2 (after B merges):
  main ← B ← C ← D ← E ← F ← G

A 合并时机：
  A 可在 Wave 1 任意时刻合入 main。但 A 与 B/C–G 的整合（将内存 FAISS 替换为
  pgvector、将 dict graph 替换为 knowledge_nodes/edges 表、将管线接入 Task 调度）
  在 Wave 2 全部完成后统一进行。

Post-Wave-2 integration:
  Agent A pipeline ← 接入 →
    Agent D (novel → chapters, RAG → pgvector)
    Agent F (task lifecycle: pending→preprocessing→converting→completed)
    Agent E (script output storage)
```

## 7. Test Summary

| Agent | Test Count | pytest Marker | Coverage Target |
|-------|-----------|---------------|-----------------|
| A | 10 | `@pytest.mark.pipeline` | ≥80% per module |
| B | 10 | `@pytest.mark.db` | ≥90% (core infra) |
| C | 6 | `@pytest.mark.auth` | ≥85% |
| D | 5 | `@pytest.mark.novel` | ≥85% |
| E | 5 | `@pytest.mark.scripts` | ≥85% |
| F | 6 | `@pytest.mark.tasks` | ≥85% |
| G | 5 | `@pytest.mark.editor` | ≥85% |
| **Total** | **47** | | |

All tests use `pytest-asyncio` for async endpoints. DB-dependent tests (B–G) run against a local PostgreSQL via `pytest-postgresql` or a dedicated test database.
