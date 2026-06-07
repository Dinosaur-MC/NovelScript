# NovelScript (析幕) 软件设计说明书

- **项目名称**：NovelScript (析幕) – AI 驱动的长篇小说到结构化剧本转换系统
- **文档版本**：v2.1.0
- **日期**：2026-06-06
- **作者**：Dinosaur_MC
- **关联文档**：[SRS 需求规格说明书](./SRS%20需求规格说明书.md) · [YAML Schema 设计说明](./YAML_Schema_设计说明.md)

---

## 1. 设计概述

### 1.1 设计目标

本系统旨在将数十万字非结构化小说文本自动转换为符合影视工业标准的结构化剧本（YAML/JSON/Fountain）。核心设计目标：

| 目标                | 约束条件                                                                                 |
| :------------------ | :--------------------------------------------------------------------------------------- |
| **确定性管线**      | 管道输出 100% 通过 Pydantic V2 严格校验，LLM 输出非法时自动修复（最大 2 次重试）         |
| **双向溯源**        | 每个剧本元素携带 `source_ref`（`chapter_id` + `offset`），实现原文↔剧本毫秒级联动        |
| **All-in-One 存储** | 以 PostgreSQL 18 作为唯一数据底座，集成 pgvector 向量检索 + JSONB 文档存储               |
| **成本可控**        | 严格区分 DeepSeek-v4-pro（知识图谱/一致性检查）与 DeepSeek-v4-flash（场景生成/对话）路由 |
| **单人可交付**      | 72 小时极限开发，架构简化为 Postgres → FastAPI → React 三层                              |

### 1.2 设计原则

| 原则               | 说明                                                                                                                           |
| :----------------- | :----------------------------------------------------------------------------------------------------------------------------- |
| **严格校验**       | 所有 LLM 输出在进入系统前必须通过 Pydantic V2 模型校验，不通过则触发 Auto-Fix 循环                                             |
| **溯源锚定**       | `source_ref` 下沉至每个 Scene 与 Element，基于字符偏移量 (Offset) 的双向高亮联动                                               |
| **结构化兜底**     | 每个结构化字段同时保留原始文本与拆解子字段，解析失败时降级回退到原始文本                                                       |
| **逻辑与物理解耦** | YAML 使用"逻辑块 (Logical Block)"聚合（如将角色、括号提示、对白聚合为 `dialogue_block`），导出引擎负责拆解为 Fountain "物理行" |
| **版本控制友好**   | YAML 文本格式天然适配 Git diff/merge，支持异步协作与全历史溯源                                                                 |

### 1.3 技术栈确认

| 层       | 技术选型                                                                                               |
| :------- | :----------------------------------------------------------------------------------------------------- |
| **前端** | React 19 + TypeScript + Vite, React Router v7, Zustand, Ant Design 6, Monaco Editor, TipTap, ReactFlow |
| **后端** | Python 3.13, FastAPI (sync, psycopg2), Uvicorn, SQLAlchemy + psycopg2-binary, LangChain, sse-starlette |
| **数据** | PostgreSQL 18 + pgvector + uuid-ossp + pg_trgm                                                    |
| **AI**   | DeepSeek V4 Pro (1M ctx/384K output) — 知识图谱/一致性检查; DeepSeek V4 Flash (1M ctx/384K output) — 场景生成/对话/摘要/补丁 |
| **部署** | Docker Compose (Frontend + Backend + PostgreSQL), Nginx 反向代理                                  |

> **注意**：后端使用**同步 `psycopg2`** 驱动（非 asyncpg），避免 Windows ProactorEventLoop 兼容性问题。管道引擎内部使用 `asyncio` 做并行章节转换，但 FastAPI 路由和 DB 层均为同步实现。

## 2. 系统架构设计

### 2.1 总体架构

系统摒弃传统的 "MySQL + FAISS + Neo4j" 多组件堆砌，采用 **PostgreSQL All-in-One** 架构：pgvector 替代 FAISS 做向量检索，JSONB + 独立点边表 (`knowledge_nodes`/`knowledge_edges`) 替代 Neo4j 做图存储与 GraphRAG 遍历，8 张关系表管理用户、小说、任务管线、操作历史、AI 对话与系统审计。

```mermaid
flowchart TB
    subgraph Browser["🖥 Browser: React 19 + TS + Ant Design"]
        direction TB
        TipTap["TipTap<br/>（原文阅读）"]
        Monaco["Monaco Editor<br/>（YAML 编辑）"]
        Flow["ReactFlow + Tab<br/>（图谱/预览/AI）"]
    end

    Browser -->|"HTTP/REST"| Nginx["Nginx Reverse Proxy<br/>& Static Server"]
    Browser -->|"SSE (进度推送)"| Nginx

    Nginx --> FastAPI

    subgraph FastAPI["FastAPI Application Server (Python 3.13)"]
        direction TB
        Auth["/api/auth/*<br/>（用户认证）"]
        Novel["/api/novel/*<br/>（任务管线）"]
        ScriptApi["/api/scripts/*<br/>（剧本管理）"]
        EdApi["/api/editor/*<br/>（AI 编辑）"]
        Router["LLM Router<br/>（Pro ↔ Flash）"]
        DAL["Data Access Layer<br/>（Asyncpg + SQLModel）"]
    end

    FastAPI --> PostgreSQL

    subgraph PostgreSQL["PostgreSQL 18 (All-in-One Data Hub)"]
        direction BT
        Rel["关系数据<br/>users, novels, tasks, chapters<br/>knowledge_nodes, knowledge_edges<br/>operations, dialogues, audit_logs"]
        Vec["向量数据<br/>pgvector (HNSW 索引)<br/>chapters.embedding<br/>knowledge_nodes.embedding"]
        Doc["图 / 文档<br/>JSONB + GIN + JSONPath<br/>图遍历 / GraphRAG"]
    end
```

### 2.2 前端架构

```
frontend/app/
├── root.tsx                # 根布局 (Inter 字体, ErrorBoundary)
├── routes.ts               # 路由配置
├── routes/
│   └── home.tsx            # 主工作台页面 (三栏布局容器)
├── components/
│   ├── novel-reader/       # TipTap 原文阅读器 (左栏)
│   ├── script-editor/      # Monaco YAML 编辑器 (中栏)
│   ├── script-preview/     # 剧本可视化预览 (右栏 Tab1)
│   ├── knowledge-graph/    # ReactFlow 知识图谱 (右栏 Tab2)
│   ├── ai-chat/            # AI 对话面板 (右栏 Tab3)
│   ├── task-bar/           # 顶栏：Logo + 任务状态 + 导出菜单
│   └── status-bar/         # 底栏：进度条 + 系统日志
├── stores/                 # Zustand stores
│   ├── task-store.ts       # 任务状态 (status, progress, error)
│   ├── script-store.ts     # 剧本数据 (YAML/Fountain, source_refs)
│   ├── editor-store.ts     # 编辑器状态 (光标、选区、Undo/Redo)
│   └── ui-store.ts         # UI 状态 (面板宽度、Tab 切换)
├── hooks/                  # 自定义 hooks (SSE 订阅, 溯源跳转)
└── app.css                 # Tailwind CSS v4 + Inter 字体
```

- **状态管理 (Zustand)**：4 个独立 store，按领域拆分。跨 store 通信通过组件层调用多个 store action 实现。
- **SSE 进度推送**：使用 `EventSource` 订阅 `/api/v1/tasks/{task_id}/stream` 的 SSE 流，接收 `progress`/`complete`/`error` 事件，实时更新 `task-store`。

### 2.3 后端架构

```
backend/app/
├── main.py                     # FastAPI 应用工厂, lifespan (引擎池回收), CORS, 异常处理器
├── api/v1/
│   ├── __init__.py             # 统一路由树 → /api/v1/*
│   ├── auth.py                 # /api/v1/auth/* (register/login/logout/me)
│   ├── novels.py               # /api/v1/novels/* (upload/list/get/update/delete)
│   ├── scripts.py              # /api/v1/scripts/* (list/get/update/delete/export)
│   ├── tasks.py                # /api/v1/tasks/* (create/list/stream/status/update/resume/get)
│   └── editor.py               # /api/v1/editor/* (chat/apply_patch/undo)
├── core/
│   ├── config.py               # pydantic-settings (DB URL, API Key, ADMIN_*, LLM_*)
│   ├── security.py             # argon2 哈希, JWT 创建/解码 (sync, jti 声明)
│   ├── db.py                   # 同步 psycopg2 引擎, get_db(), init_db(), dispose_engine()
│   ├── redis.py                # Redis 连接池 (懒加载, 线程安全), get_redis() DI
│   ├── auth_middleware.py      # get_current_user (JWT 解码, 黑名单检查, 用户缓存)
│   └── celery_app.py           # Celery 单例 (Redis broker + backend)
├── models/
│   ├── http.py                 # BaseResponse(code, message, data), ErrorResponse
│   └── sql.py                  # 9 表 SQLModel 定义
├── services/
│   ├── base.py                 # BaseCRUD[T] — 通用增删改查
│   ├── progress.py             # ProgressManager 单例 (queue.Queue 每任务, 线程安全)
│   ├── pipeline_executor.py    # 后台守护线程, DB 章节优先, SSE 事件推送
│   ├── sse.py                  # push_progress() → ProgressManager 委托
│   ├── token_blacklist.py      # JWT 撤销 — bl:{jti} 存入 Redis, TTL 自动过期
│   ├── rate_limiter.py         # 固定窗口限流 — Redis INCR + EXPIRE (原子 SET NX)
│   └── user_cache.py           # 用户资料缓存 — user:{id}, 300s TTL
└── db/
    └── init.sql                # 9 表 DDL + 3 扩展 + HNSW + GIN 索引

backend/cli/                    # Pipeline 引擎 (11 模块)
├── models.py                   # Chapter, ParagraphGroup, Scene, Script, KG
├── chunker.py                  # 正则切分 (第X章) + LLM 回退 (JSON mode)
├── paragraph_splitter.py       # 段落级对齐切分 (短段合并, 预算分组)
├── summarizer.py               # 逐章客观摘要 (Flash, 100-200 字)
├── rag_builder.py              # FAISS 索引 (OpenRouter embedding) + 关键词回退
├── graphrag_builder.py         # 知识图谱提取 (Pro, RAG 跨章节上下文)
├── converter.py                # 章节→场景 (Flash, paragraph groups, 前情提要)
├── optimizer.py                # 分批一致性检查 (Pro, 位置索引 source_ref 恢复)
├── llm_router.py               # 模型路由, 上下文/输出限制, invoke_with_retry()
├── exporter.py                 # YAML/JSON 导出
└── pipeline.py                 # 7 阶段编排 (3 入口: file/directory/chapters)
```

**分层职责**：

- **api/** — 薄路由层，Pydantic 参数校验，SSE 端点，业务逻辑委托给 services
- **services/** — 后台执行、SSE 事件分发、CRUD 基类
- **cli/** — Pipeline 引擎核心，每个模块独立可单独测试（166 测试覆盖）
- **models/** — Pydantic V2 模型 + SQLModel 表定义，是 LLM 输出的强制校验门
- **core/** — 配置、安全、DB 生命周期（引擎池回收 atexit + lifespan + test teardown）

## 3. 核心管道设计 (Pipeline)

### 3.1 7 阶段管道总览

Pipeline 将小说→剧本转换分解为 7 个专业化阶段，阶段间**松耦合**，每个阶段有独立的前向依赖与回退策略：

```
1. Chunking      —— 正则 (第X章) + LLM 回退 (Flash)
2. Summarize     —— 逐章客观摘要 (Flash, 并行)
3. RAG Index     —— FAISS 向量索引 (OpenRouter embedding)
4. GraphRAG      —— 知识图谱提取 (Pro, 带 RAG 跨章节上下文)
5. Conversion    —— 章节→场景 (Flash, 并行, 段落组输入)
6. Optimization  —— 跨场景一致性 (Pro, 按场景分批)
7. Narrative Summary —— 全局故事概述 (Flash, 从章摘要合成)
```

### 3.2 Stage 1: 章节切分 (Chunking)

- **模型**：DeepSeek V4 Flash（回退时）
- **策略**：正则优先匹配 `第[零一二三四五六七八九十百千0-9]+章`，匹配失败或短章节（avg<5 字符）则触发 LLM 回退
- **特殊路径**：目录输入（每 `.txt` 文件一章）/ DB 章节持久化（跳过拆分）
- **LLM 回退**：JSON mode，Pydantic 校验 `{chapters: [{title, body}]}`

### 3.3 Stage 2: 逐章摘要 (Summarize, 并行)

- **模型**：DeepSeek V4 Flash
- **设计**：每章独立并行执行，无跨章依赖 → 保持并行性
- **输出**：100-200 字客观事件摘要（仅事实描述，不推论/评价）
- **用途**：存入 `meta.chapter_summaries`，供 Converter 的前情提要和 Narrative Summary 使用

### 3.4 Stage 3: RAG 索引构建

- **Embedding**：OpenRouter `nvidia/llama-nemotron-embed-vl-1b-v2:free`（`encoding_format=float`）
- **索引**：内存 FAISS（每章全文存为 Document）
- **回退**：FAISS 失败 → 关键词字符重叠搜索（`fallback_texts` 传入章节全文）

### 3.5 Stage 4: 知识图谱提取 (GraphRAG)

- **模型**：DeepSeek V4 Pro（JSON mode）
- **输入增强**：RAG 为每章检索跨章节语义关联上下文（≤3K 字符），注入 KG 提取 prompt
- **切片**：段落组对齐（`ParagraphSplitter`），每章 ≤`context_chars()` 预算
- **输出**：`KnowledgeNode` 列表（character/location/item/event/organization）+ `KnowledgeEdge` 列表
- **回退**：失败返回空 `KnowledgeGraph()`

### 3.6 Stage 5: 场景转换 (Conversion, 并行)

- **模型**：DeepSeek V4 Flash（JSON mode, `max_tokens=8000`）
- **输入**：
  - 段落组对齐的章节文本（ParagraphSplitter，杜绝跨句截断）
  - RAG 跨章节上下文（每片段 ≤2000 字符）
  - 知识图谱摘要（角色 + 关系）
  - 本章前情摘要
- **输出**：`SceneList`（通过 Pydantic 校验 + `source_ref` 注入`）
- **回退**：失败返回 `[]`（该章静默丢失，不阻断管线）
- **重试**：应用层指数退避，最大 2 次（`scene_conversion`）

### 3.7 Stage 6: 一致性优化 (Optimization, 分批)

- **模型**：DeepSeek V4 Pro（JSON mode, `max_tokens=4000`）
- **分批策略**：按 `_BATCH_BUDGET=10K` 字符将场景拆为独立批次，以场景为原子单位（不跨场景切分）；单场景超预算也允许通过
- **source_ref 恢复**：优化后按**位置索引**（非 scene_id）从原始场景恢复溯源锚点
- **回退**：批次失败保留原始场景
- **重试**：最大 3 次（`consistency_check`）——管线末端，损失成本最高

### 3.8 Stage 7: 叙事摘要 (Narrative Summary)

- **模型**：DeepSeek V4 Flash
- **输入**：逐章摘要拼接（"第 1 章摘要: …第 2 章摘要: …"）
- **输出**：一段话（≤300 字）全局故事概述
- **回退**：程序化摘要（角色数+地点数+事件数）

### 3.9 段落级切分 (Paragraph Splitter)

- **输入**：章节全文
- **切分**：按 `\n{2,}` 边界（空行=段落边界）→ 短段落（≤32 字）合并 → 按 Token 预算累加分组
- **保证**：每个 ParagraphGroup 以完整段落结束，LLM 从不收到截断的句子
- **预算**：由 `context_chars(stage)` 自动计算（从模型名匹配上下文窗口，保守 CJK 密度 0.6 chars/token，60% 窗口为输入预算）

### 3.10 Auto-Fix 与重试

- **校验**：所有 JSON 输出通过 `JsonOutputParser(pydantic_object=Model)` + `Model.model_validate()` 双阶段校验
- **重试**：应用层 `invoke_with_retry()` 处理可重试异常（`APIConnectionError`, `APITimeoutError`, `RateLimitError`, `InternalServerError`, `httpx.ConnectError` 等），指数退避（base=1s, factor=2, max=30s）加随机抖动
- **不可重试**：4xx 客户端错误直接上抛
- **全局覆盖**：`LLM_MAX_RETRIES` 环境变量统一调整所有阶段

## 4. 模型路由策略

### 4.1 Pro / Flash 分工逻辑

| 任务类型                | 推荐模型          | 设计依据                                           |
| :---------------------- | :---------------- | :------------------------------------------------- |
| 全局知识图谱提取        | DeepSeek V4 Pro   | 需要深度理解全文、实体关系抽取，要求最强推理能力   |
| 场景转换与重构          | DeepSeek V4 Flash | 模式化生成任务，Flash 成本效益高，速度满足迭代需求 |
| 全量 Scene 一致性检查   | DeepSeek V4 Pro   | 需要全局视野审视所有场景，发现潜在矛盾             |
| 章节切分（回退）        | DeepSeek V4 Flash | 轻量语义任务，当正则可覆盖 90% 时仅作补充          |
| 逐章摘要生成            | DeepSeek V4 Flash | 低复杂度文本总结，Pro 浪费算力与成本               |
| 叙事摘要合成            | DeepSeek V4 Flash | 低复杂度文本总结                                   |
| AI 对话 / 上下文问答    | DeepSeek V4 Flash | 对延迟要求高，Flash 高速推理提供流畅对话体验       |
| Patch 生成 (结构化修改) | DeepSeek V4 Flash | 符合 RFC 6902 的模式化输出，Flash 足以胜任         |

### 4.2 模型感知上下文预算

- **上下文窗口**：`_MODEL_LIMITS` 表按模型名记录（DeepSeek V4: 1M tokens / 384K output）
- **自动计算**：`context_chars(stage)` → `context_tokens * 0.6 * 0.6`（CJK 密度 × 输入使用率）
- **手动覆盖**：`.env` 中 `LLM_CONTEXT_WINDOW` 和 `LLM_MAX_OUTPUT_TOKENS` 可全局覆盖
- **每阶段 `max_tokens`**：`min(per_stage_cap, model_max_output)` → 防止输出截断和成本失控

### 4.3 代码实现

```python
# 模型路由表
MODEL_ROUTING = {
    "global_extraction":  "deepseek-v4-pro",
    "scene_conversion":   "deepseek-v4-flash",
    "consistency_check":  "deepseek-v4-pro",
    "chapter_split":      "deepseek-v4-flash",
    "chapter_summary":    "deepseek-v4-flash",
    "ai_chat":            "deepseek-v4-flash",
}

# 上下文/输出限制
_MODEL_LIMITS = {
    "deepseek-v4-pro":   {"context": 1_000_000, "max_output": 384_000},
    "deepseek-v4-flash": {"context": 1_000_000, "max_output": 384_000},
}
```

### 4.4 成本控制与降级策略

- **Pro 模型调用**：仅用于知识图谱提取（Stage 4）与全量一致性检查（Stage 6）
- **Flash 模型调用**：承担 Stage 1/2/5/7 及编辑器主要负载
- **逐阶段回退**：每阶段失败独立降级（KG→空图, 转换→空列表, 优化→原始场景）
- **段落级切分**：避免裸字符截断导致的场景丢失和重复 LLM 调用

## 5. 数据模型设计

### 5.1 YAML Schema 四层架构

详见 [YAML Schema 设计说明](./YAML_Schema_设计说明.md)，核心分层：

| 层级                       | 职责                                                             |
| :------------------------- | :--------------------------------------------------------------- |
| **Layer 0: Fountain 同构** | 100% Fountain 1.1 往返保真（8 种元素类型, Title Page, Boneyard） |
| **Layer 1: 结构增强**      | 分解 heading 字段, `dialogue_block` 聚合, `source_ref` 3D 溯源   |
| **Layer 2: 叙事扩展**      | 闪回/闪前标记、多时间线 ID、画外音子类型、意识流标记等           |
| **Layer 3: 渲染与交付**    | Fountain 导出 + 直接 PDF 渲染                                    |

**完整 YAML Schema 示例**（见 SRS §6.1），顶层结构：

```text
script
├── meta          # 标题、作者、模型、时间戳、版本
├── summary       # 全局梗概
├── characters[]  # 角色列表 (id, name, description)
├── scenes[]      # 场景序列
│   ├── scene_id
│   ├── heading            # 场标 (内景/外景 . 地点 - 时间)
│   ├── location / time_of_day  # 拆解子字段
│   ├── characters_present[]    # 出场角色
│   └── elements[]             # 剧本元素 (action/dialogue/shot...)
│       ├── type
│       ├── content / line
│       └── source_ref           # { chapter_id, offset }
└── knowledge_graph                # 逻辑视图；物理层由 knowledge_nodes + knowledge_edges 表存储
    ├── nodes[]       # 实体节点 (角色、地点、关键物品)  → 同步至 knowledge_nodes 表
    └── edges[]       # 关系边 (relation, weight)        → 同步至 knowledge_edges 表
```

### 5.2 YAML 快照 + JSON Patch 混合存储模型

单一存储机制无法同时满足：低延迟实时编辑、可靠长期状态管理、精确历史追踪。本系统采用**混合模型**：

| 存储机制       | 记录内容                    | 优势                                     | 劣势                                   | 适用场景                  |
| :------------- | :-------------------------- | :--------------------------------------- | :------------------------------------- | :------------------------ |
| **YAML 快照**  | 应用在某时间点的完整状态    | 恢复状态简单高效；保证完整性；易实现重做 | 存储空间消耗大                         | 手动/自动保存点；阶段结束 |
| **JSON Patch** | 状态的增量式变更 (RFC 6902) | 存储效率极高；天然支持撤销；适合高频编辑 | 恢复早期状态计算开销大；依赖序列完整性 | 实时编辑；AI 补丁应用     |

**协同逻辑**：

1. 阶段完成 / 手动保存时 → 生成 YAML 快照存入 `operations.previous_snapshot`
2. 每次细粒度编辑（用户输入 / AI Patch）→ 记录 JSON Patch 存入 `operations.diff_json`
3. 撤销时 → 优先使用 JSON Patch 逆向操作（即时响应）；回溯超过 5 步或跨快照时 → 加载最近快照 + 重放区间 Patch

### 5.3 撤销/重做历史栈

```mermaid
flowchart LR
    subgraph Undo["Undo Stack（LIFO）"]
        direction LR
        U1["Patch N（最新操作）"]
        U2["Patch N-1"]
        U3["..."]
        U4["Patch 1"]
        U5["← Snapshot Anchor"]
    end

    Undo -->|"撤销 → 移入"| Redo

    subgraph Redo["Redo Stack（LIFO）"]
        direction LR
        R1["（空，等待 Redo）"]
    end
```

- **Undo**：从 Undo Stack 弹出最近 Patch，计算逆向 Patch 并应用 → 将该 Patch 移入 Redo Stack
- **Redo**：从 Redo Stack 弹出 Patch，正向应用 → 移回 Undo Stack
- **快照锚点**：加载新快照时清空 Redo Stack（因为"未来"已不再有意义）
- **容量限制**：最多保留 5 步连续 Undo/Redo，超出时自动创建新快照并裁剪旧 Patch 序列

### 5.4 双向溯源 (source_ref) 机制

```mermaid
flowchart TB
    subgraph Input["📖 小说原文层"]
        direction LR
        NovelCh["<b>Chapter ch_02</b><br/>offset: [1450, 1520]<br/><br/>『林明疲惫地靠在座椅上，<br/>手里把玩着一个旧式怀表。<br/>艾娃静静地站在他身后。』"]
    end

    Input -->|"Stage 1 → 2 → 3<br/>LLM 管道转换"| Script

    subgraph Script["🎬 结构化剧本层"]
        direction LR
        SceneH["<b>Scene S001</b><br/>内景. 废弃飞船驾驶舱 - 夜晚"]
        Action["<b>Element #1</b> · action<br/>控制台上闪烁着微弱的红光…"]
        Dialogue["<b>Element #2</b> · dialogue<br/>char_01 林明（自嘲地笑）<br/>『你说，宇宙的边缘到底有什么？』"]
        SceneH --> Action --> Dialogue
    end

    Script -->|"100% 强制注入"| Bridge

    Bridge{"<b>🎯 source_ref 溯源锚点</b><br/><br/>chapter_id: ch_02<br/>offset: [1450, 1520]"}

    Bridge -->|"前向追溯"| Forward["<b>点击剧本元素</b><br/>左栏原文自动滚动<br/>并高亮对应段落 ✅"]
    Bridge -->|"后向追溯"| Backward["<b>点击原文段落</b><br/>右栏 & 中栏<br/>高亮所有引用元素 ✅"]
    Bridge -->|"跨阶段追溯"| Cross["<b>Stage 1 规划节点</b><br/>↕<br/><b>Stage 2/3 下游元素</b><br/>意图 → 实现全链路可查"]

```

- **前向追溯**：点击剧本元素 → 原文段落自动滚动并高亮
- **后向追溯**：点击原文段落 → 所有引用该段落的剧本元素高亮
- **跨阶段追溯**：通过 Stage 1 规划节点 → 查看所有由此规划衍生的 Stage 2/3 产出物
- **实现**：前端通过 `source_ref.offset` 定位 TipTap 文档位置；后端通过 `chapter_id + offset` 查询反向引用

### 5.5 持久化存储 DDL

利用 pgvector 和 JSONB 实现 All-in-One 架构。相比 SRS v2.0.0 初版设计（4 表），重构后的数据模型扩展至 **8 张核心表**，覆盖用户鉴权、小说实体、任务管线、知识图谱、操作历史、AI 对话与系统审计七大领域。

```sql
-- 启用必要插件
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pg_trgm;         -- 文本模糊搜索 (知识图谱实体名称)

-- ============================================================
-- 0. 用户表 — 账户与鉴权
-- ============================================================
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    username VARCHAR(100) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,         -- bcrypt / argon2
    display_name VARCHAR(100),
    avatar_url TEXT,
    role VARCHAR(20) DEFAULT 'user'
        CHECK (role IN ('admin', 'user')),
    is_active BOOLEAN DEFAULT TRUE,
    last_login_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_username ON users(username);

-- ============================================================
-- 1. 小说主表 — 原文存储的独立实体
--     (与任务解耦：同一部小说可多次执行 Pipeline)
-- ============================================================
CREATE TABLE novels (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    title VARCHAR(500) NOT NULL,
    author VARCHAR(255),
    source_text TEXT NOT NULL,                   -- 原始全文 (从 tasks 迁移至此)
    word_count INT,
    language VARCHAR(10) DEFAULT 'zh'
        CHECK (language IN ('zh', 'en')),
    status VARCHAR(20) DEFAULT 'draft'
        CHECK (status IN ('draft', 'processing', 'completed')),
    metadata JSONB,                              -- { genre, tags, source_url, notes }
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_novels_user ON novels(user_id);
CREATE INDEX idx_novels_status ON novels(status);

-- ============================================================
-- 2. 任务表 — 一次 Pipeline 运行
--     引用 novels，去除 source_text，新增 pipeline_config
-- ============================================================
CREATE TABLE tasks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    novel_id UUID NOT NULL REFERENCES novels(id) ON DELETE CASCADE,
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    progress INT DEFAULT 0
        CHECK (progress >= 0 AND progress <= 100),
    summary TEXT,
    characters_json JSONB,                       -- 本次运行提取的角色列表
    script_yaml TEXT,                            -- 剧本 YAML
    script_json JSONB,                           -- 剧本 JSON (支持 JSONPath)
    script_fountain TEXT,                        -- 剧本 Fountain
    error_message TEXT,
    pipeline_config JSONB,                       -- { model_versions, chunk_size, overlap, ... }
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_tasks_novel ON tasks(novel_id);
CREATE INDEX idx_tasks_user ON tasks(user_id);
CREATE INDEX idx_tasks_status ON tasks(status);

-- ============================================================
-- 3. 章节表 — 属于小说 (非任务)
--     章节切分后落库，pgvector HNSW 索引加速 RAG 检索
-- ============================================================
CREATE TABLE chapters (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    novel_id UUID NOT NULL REFERENCES novels(id) ON DELETE CASCADE,
    chapter_index INT NOT NULL,
    title VARCHAR(255),
    content TEXT NOT NULL,
    embedding vector(1536),                      -- 文本语义向量
    metadata JSONB,                              -- { word_count, start_offset, end_offset }
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX ON chapters USING hnsw (embedding vector_cosine_ops);
CREATE INDEX idx_chapters_novel ON chapters(novel_id, chapter_index);

-- ============================================================
-- 4. 知识图谱 — 实体节点
--     从 novels 提取，支持 GraphRAG 图遍历与语义搜索
-- ============================================================
CREATE TABLE knowledge_nodes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    novel_id UUID NOT NULL REFERENCES novels(id) ON DELETE CASCADE,
    task_id UUID REFERENCES tasks(id) ON DELETE SET NULL,   -- 提取来源任务
    node_type VARCHAR(50) NOT NULL
        CHECK (node_type IN (
            'character', 'location', 'item',
            'organization', 'event', 'concept'
        )),
    name VARCHAR(255) NOT NULL,
    aliases TEXT[],                              -- PostgreSQL 数组: 别名列表
    description TEXT,
    properties JSONB,                            -- { gender, age, faction, ... }
    embedding vector(1536),                      -- 节点语义向量 (GraphRAG 检索)
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX ON knowledge_nodes USING hnsw (embedding vector_cosine_ops);
CREATE INDEX idx_kn_nodes_novel ON knowledge_nodes(novel_id);
CREATE INDEX idx_kn_nodes_type ON knowledge_nodes(node_type);
CREATE INDEX idx_kn_nodes_name ON knowledge_nodes USING gin (name gin_trgm_ops);

-- ============================================================
-- 5. 知识图谱 — 关系边
--     支持图遍历: 递归 CTE / JSONPath 查询角色关系网
-- ============================================================
CREATE TABLE knowledge_edges (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    novel_id UUID NOT NULL REFERENCES novels(id) ON DELETE CASCADE,
    task_id UUID REFERENCES tasks(id) ON DELETE SET NULL,
    source_node_id UUID NOT NULL REFERENCES knowledge_nodes(id) ON DELETE CASCADE,
    target_node_id UUID NOT NULL REFERENCES knowledge_nodes(id) ON DELETE CASCADE,
    relation VARCHAR(100) NOT NULL,              -- 'friend_of', 'enemy_of', 'located_in', 'owns' ...
    weight FLOAT DEFAULT 1.0,                    -- 关系强度 [0, 1]
    evidence TEXT,                               -- 原文依据 (溯源)
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_ke_edges_novel ON knowledge_edges(novel_id);
CREATE INDEX idx_ke_edges_src ON knowledge_edges(source_node_id);
CREATE INDEX idx_ke_edges_tgt ON knowledge_edges(target_node_id);
CREATE INDEX idx_ke_edges_rel ON knowledge_edges(relation);

-- ============================================================
-- 6. 操作日志表 — JSON Patch + YAML 快照混合 (新增 user_id)
-- ============================================================
CREATE TABLE operations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    type VARCHAR(50) NOT NULL
        CHECK (type IN ('manual_edit', 'ai_patch', 'snapshot', 'rollback')),
    target_path TEXT,                            -- JSON Pointer 路径
    diff_json JSONB,                             -- RFC 6902 JSON Patch
    previous_snapshot JSONB,                     -- YAML 快照 (仅在 type='snapshot' 时)
    applied BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_ops_task_time ON operations(task_id, created_at DESC);

-- ============================================================
-- 7. AI 对话记录表 — 新增 system 角色 + metadata
-- ============================================================
CREATE TABLE dialogues (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    role VARCHAR(20) NOT NULL
        CHECK (role IN ('user', 'assistant', 'system')),
    content TEXT NOT NULL,
    patch_json JSONB,                            -- 若消息包含 Patch 则记录
    metadata JSONB,                              -- { scene_id, selected_text, model_used, token_count }
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_dialog_task_time ON dialogues(task_id, created_at);

-- ============================================================
-- 8. 系统审计日志 — LLM 调用、错误追踪、操作审计
-- ============================================================
CREATE TABLE audit_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    task_id UUID REFERENCES tasks(id) ON DELETE SET NULL,
    level VARCHAR(20) NOT NULL DEFAULT 'info'
        CHECK (level IN ('debug', 'info', 'warn', 'error', 'fatal')),
    category VARCHAR(50) NOT NULL,               -- 'llm_call', 'db_query', 'validation', 'pipeline', 'auth', 'export'
    message TEXT NOT NULL,
    detail JSONB,                                -- { model, tokens, latency_ms, endpoint, status_code, ... }
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_audit_level_time ON audit_logs(level, created_at DESC);
CREATE INDEX idx_audit_category ON audit_logs(category);
CREATE INDEX idx_audit_task ON audit_logs(task_id);
-- 可选: 配置 pg_cron 定期清理 90 天前的日志
```

**表设计对比**：

| 版本    | 表数 | 覆盖领域                                                          |
| :------ | :--- | :---------------------------------------------------------------- |
| v1 (旧) | 4    | 任务 + 章节 + 操作 + 对话（小说原文内嵌于任务）                   |
| v2 (新) | 8    | 用户 + 小说 + 任务 + 章节 + 知识图谱点边 + 操作 + 对话 + 审计日志 |

**表关系概览**：

```mermaid
erDiagram
    users ||--o{ novels : "owns 1:N"
    users ||--o{ tasks : "triggers 1:N"
    users ||--o{ operations : "performs 1:N"
    users ||--o{ dialogues : "sends 1:N"
    users ||--o{ audit_logs : "generates 1:N"

    novels ||--o{ tasks : "pipeline runs 1:N"
    novels ||--o{ chapters : "contains 1:N"
    novels ||--o{ knowledge_nodes : "extracted to 1:N"
    novels ||--o{ knowledge_edges : "extracted to 1:N"

    tasks ||--o{ operations : "records 1:N"
    tasks ||--o{ dialogues : "has 1:N"
    tasks ||--o{ knowledge_nodes : "extracts 0..1:N"
    tasks ||--o{ knowledge_edges : "extracts 0..1:N"

    knowledge_nodes ||--o{ knowledge_edges : "source 1:N"
    knowledge_nodes ||--o{ knowledge_edges : "target 1:N"
```

## 6. 任务状态机与生命周期

### 6.1 状态流转

```mermaid
stateDiagram-v2
    [*] --> PENDING

    PENDING --> PREPROCESSING : POST /api/novel/preprocess/{id}
    note right of PREPROCESSING
        Stage 1: 章节切分 + 实体提取 + 向量入库
    end note

    PREPROCESSING --> CONVERTING

    CONVERTING --> CONVERTING : 失败 + 可恢复（网络波动）<br>→ POST /api/novel/resume/{id}
    note right of CONVERTING
        Stage 2+3: 场景生成 + 校验 + 优化
    end note

    CONVERTING --> COMPLETED : 成功

    CONVERTING --> FAILED : 失败（超过重试上限）

    COMPLETED --> [*]
    FAILED --> [*]
```

### 6.2 Pydantic 任务状态模型

```python
from pydantic import BaseModel, Field
from enum import Enum
from typing import Optional, List, Dict, Any
from datetime import datetime

class TaskStatus(str, Enum):
    PENDING = "pending"
    PREPROCESSING = "preprocessing"
    CONVERTING = "converting"
    COMPLETED = "completed"
    FAILED = "failed"

class TaskResponse(BaseModel):
    id: str
    novel_id: str
    user_id: Optional[str] = None
    status: TaskStatus
    progress: int = Field(ge=0, le=100)
    summary: Optional[str] = None
    characters: Optional[List[Dict[str, Any]]] = None
    script_yaml: Optional[str] = None
    script_fountain: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime
```

### 6.3 SSE 进度推送

```mermaid
sequenceDiagram
    participant Client as 🖥 Client
    participant Server as ⚙️ Server

    Client->>Server: GET /api/novel/status/{id}<br/>Accept: text/event-stream

    Server-->>Client: event: progress<br/>data: {"progress": 15, "stage": "preprocessing"}
    Server-->>Client: event: progress<br/>data: {"progress": 45, "stage": "converting"}
    Server-->>Client: event: progress<br/>data: {"progress": 80, "stage": "optimizing"}
    Server-->>Client: event: complete<br/>data: {"progress": 100, "script_yaml": "..."}
```

- **实现**：`sse-starlette` 库，后端通过 `asyncio.Queue` 收集 Pipeline 各阶段进度事件并推流
- **前端**：使用 `EventSource` API 订阅，实时更新 Zustand `task-store`

### 6.4 断点续传

- **触发条件**：转换过程中网络波动或 LLM 调用超时
- **恢复机制**：`POST /api/novel/resume/{task_id}` 读取 `chapters` 表中已成功转换的 `chapter_index`，从下一个未完成 Chunk 处继续，避免全盘重跑
- **幂等性**：已完成章节的 Scene 数据不被覆盖，仅追加新增部分

## 7. 模块详细设计

### 7.1 小说输入模块

- **输入方式**：
    - 文本粘贴：TipTap 编辑器内直接粘贴 Markdown/纯文本
    - 文件上传：`.txt` / `.md`，限制 5MB
    - URL 抓取 (P1)：`BeautifulSoup` 提取 `<article>` 或主内容区
- **章节切分**：
    1. 正则主切分：`第[零一二三四五六七八九十百千0-9]+章` 匹配中文章节标题
    2. LLM 语义兜底：正则无法匹配时调用 Flash 做语义分章
    3. 前端编辑器：展示切分结果列表，允许用户手动合并/拆分/调整顺序
- **数据流**：`输入 → 创建 novel 记录 (关联 user) → 章节切分 → chapters 表写入 (关联 novel_id) → 创建 task (关联 novel_id + user_id) → 返回章节列表给前端确认`

### 7.2 RAG 记忆构建模块

- **向量化流程**：
    1. 章节文本通过 Embedding 模型（OpenAI text-embedding-3-small 或 bge-large-zh）转化为 1536 维向量
    2. 将向量 + 原文 + 元数据存入 `chapters` 表
    3. 创建 HNSW 索引 (`vector_cosine_ops`) 加速 KNN 检索
- **检索流程**（在 Stage 2 转换时触发）：
    1. 当前章节文本 → Embedding → `pgvector` KNN 查询
    2. 返回 top-K（默认 3）最相关的前文章节片段
    3. 作为 Context 注入 Stage 2 的 Prompt，防止角色 OOC

### 7.3 剧本转换引擎

- **Scene 切分与重构**：以章为单位，结合全局知识图谱（`knowledge_nodes` + `knowledge_edges` 表查询） + RAG 检索的前文记忆，调用 Flash 模型将叙事文本转换为 Scene 序列
- **并发策略**：所有章节通过 `asyncio.gather(*tasks)` 并行执行，无信号量限制（依赖 DeepSeek 自带速率限制 + 应用层重试）。长章节通过 `ParagraphSplitter` 按段落边界分组（不跨句截断），每组不超过 `context_chars("converting")` 预算。

- **source_ref 注入**：转换后通过 `_inject_source_refs()` 按内容匹配（精确→前缀→估算三级回退）为每个 Element 强制填充 `source_ref = {chapter_id, offset, confidence}`。优化阶段通过**位置索引**恢复溯源锚点（而非 scene_id 匹配，因 LLM 可能修改 ID）。

### 7.4 AI 编辑与 Patch 模块

- **上下文感知对话**：
    1. 用户提问时，自动获取当前选中 Scene、相关角色设定、原文片段
    2. 组装为 System Prompt + 上下文 + 用户消息，调用 Flash 模型
- **Patch 生成**：
    - AI 回复中若包含结构化修改建议，同步生成符合 RFC 6902 的 JSON Patch
    - 格式：`{ "op": "replace", "path": "/scenes/1/location", "value": "图书馆" }`
    - Patch 在应用前经过 Schema 验证，确保修改后的 YAML 仍然合法
- **Undo/Redo**：见 §5.3

### 7.5 导出模块

- **YAML 导出**：从 `tasks.script_yaml` 读取，通过 `/api/scripts/{id}/export?format=yaml` 返回文件流
- **JSON 导出**：从 `tasks.script_json` 读取并序列化，通过 `/api/scripts/{id}/export?format=json` 返回
- **Fountain 导出**：
    1. 遍历 Scene 序列
    2. Scene heading → `INT./EXT. 地点 - 时间`
    3. Action element → 纯文本段落
    4. Dialogue element → `角色名\n(括号提示)\n对白内容`
    5. 在文件头部注入 Title Page 元数据
    6. 一键下载 `.fountain` 文件

## 8. API 接口设计

### 8.1 RESTful 端点签名

#### 8.1.0 用户认证 (`/api/auth`)

| 方法   | 路径                 | 说明                                   |
| :----- | :------------------- | :------------------------------------- |
| `POST` | `/api/auth/register` | 用户注册 (username + email + password) |
| `POST` | `/api/auth/login`    | 用户登录，返回 session token           |
| `POST` | `/api/auth/logout`   | 注销当前会话                           |
| `GET`  | `/api/auth/me`       | 获取当前用户信息                       |

**POST /api/auth/register**

```json
// Request
{ "username": "writer01", "email": "a@b.com", "password": "…" }
```

```json
// Response 201
{ "code": 0, "data": { "user_id": "uuid", "username": "writer01" } }
```

**POST /api/auth/login**

```json
// Request
{ "email": "a@b.com", "password": "…" }
```

```json
// Response 200
{
    "code": 0,
    "data": {
        "token": "session-jwt-or-uuid",
        "user": { "id": "uuid", "username": "writer01", "role": "user" }
    }
}
```

- **认证方式**：`Authorization: Bearer <token>` 头传递会话 token
- **密码存储**：bcrypt / argon2 哈希
- **P2 预留**：OAuth2 (GitHub/Google) 第三方登录

#### 8.1.1 任务管理 (`/api/novel`)

| 方法   | 路径                              | 说明                                                           |
| :----- | :-------------------------------- | :------------------------------------------------------------- |
| `POST` | `/api/novel/upload`               | 上传小说文本 (multipart 或 JSON)                               |
| `POST` | `/api/novel/preprocess/{task_id}` | 启动预处理 (章节切分 + 实体提取)                               |
| `GET`  | `/api/novel/status/{task_id}`     | 查询任务状态 (支持 SSE 流式进度)                               |
| `POST` | `/api/novel/convert/{task_id}`    | 启动剧本转换                                                   |
| `POST` | `/api/novel/resume/{task_id}`     | 断点续传                                                       |
| `GET`  | `/api/novel/export/{task_id}`     | 导出剧本文件（快捷方式 → 重定向至 `/api/scripts/{id}/export`） |

**POST /api/novel/upload**

```json
// Request (JSON body)
{ "content": "第一章\n..." }
// 或 multipart/form-data (file)
```

```json
// Response 200
{
    "code": 0,
    "message": "上传成功",
    "data": {
        "novel_id": "uuid-novel",
        "task_id": "uuid-task",
        "chapters": [
            { "index": 1, "title": "第一章" },
            { "index": 2, "title": "第二章" }
        ]
    }
}
```

**GET /api/novel/status/{task_id}** (SSE)

```text
event: progress
data: {"progress": 30, "status": "converting", "stage": "scene_generation"}

event: progress
data: {"progress": 70, "status": "converting", "stage": "optimization"}

event: complete
data: {"progress": 100, "novel_id": "uuid-novel", "task_id": "uuid-task", "status": "completed", "script_yaml": "..."}
```

#### 8.1.2 AI 编辑 (`/api/editor`)

| 方法   | 路径                                | 说明                 |
| :----- | :---------------------------------- | :------------------- |
| `POST` | `/api/editor/chat/{task_id}`        | AI 对话 (上下文感知) |
| `POST` | `/api/editor/apply_patch/{task_id}` | 应用 AI 生成的 Patch |
| `POST` | `/api/editor/undo/{task_id}`        | 撤销最近操作         |

**POST /api/editor/chat/{task_id}**

```json
// Request
{ "message": "把第2场的地点改为图书馆", "scene_id": "S002" }
```

```json
// Response
{
    "code": 0,
    "data": {
        "reply": "好的，已生成修改建议。",
        "patch": {
            "op": "replace",
            "path": "/scenes/1/location",
            "value": "图书馆"
        }
    }
}
```

#### 8.1.3 剧本管理 (`/api/scripts`)

剧本作为独立资源暴露 CRUD 端点，与任务管线解耦——用户从 Monaco 编辑器的直接修改、剧本版本对比、跨任务复用均通过此组端点完成。

| 方法     | 路径                            | 说明                                          |
| :------- | :------------------------------ | :-------------------------------------------- |
| `GET`    | `/api/scripts`                  | 剧本列表 (`?novel_id=&status=&page=&limit=`)  |
| `GET`    | `/api/scripts/{script_id}`      | 获取剧本详情 (含完整 YAML/JSON/Fountain)      |
| `PUT`    | `/api/scripts/{script_id}`      | 更新剧本 YAML（Monaco 编辑器手动保存）        |
| `DELETE` | `/api/scripts/{script_id}`      | 删除剧本及关联数据                            |
| `GET`    | `/api/scripts/{script_id}/diff` | 对比两次保存的差异（`?from=&to=`）            |
| `GET`    | `/api/scripts/{id}/export`      | 导出指定格式 (`?format=yaml\|json\|fountain`) |

**GET /api/scripts?novel_id=uuid**

```json
// Response 200
{
    "code": 0,
    "data": {
        "total": 3,
        "items": [
            {
                "script_id": "uuid-s1",
                "novel_id": "uuid-novel",
                "task_id": "uuid-task",
                "status": "completed",
                "scene_count": 12,
                "character_count": 8,
                "created_at": "2026-06-05T10:00:00Z"
            }
        ]
    }
}
```

**GET /api/scripts/{script_id}**

```json
// Response 200
{
    "code": 0,
    "data": {
        "script_id": "uuid-s1",
        "novel_id": "uuid-novel",
        "task_id": "uuid-task",
        "script_yaml": "meta:\n  title: ...",
        "script_json": { "meta": {}, "scenes": [] },
        "script_fountain": "Title: ...\n\nINT. ...",
        "characters": [{ "id": "char_01", "name": "林明" }],
        "knowledge_graph": {
            "nodes": [],
            "edges": []
        },
        "updated_at": "2026-06-05T12:00:00Z"
    }
}
```

**PUT /api/scripts/{script_id}**

```json
// Request — 用户在中栏 Monaco 编辑器直接修改后点击"保存"
{
    "script_yaml": "meta:\n  title: 星辰低语\nscenes:\n  - scene_id: S001\n    heading: ..."
}
```

```json
// Response 200
{
    "code": 0,
    "message": "保存成功",
    "data": {
        "script_id": "uuid-s1",
        "updated_at": "2026-06-05T12:05:00Z",
        "validation": { "valid": true, "errors": [] }
    }
}
```

- **保存时触发 Pydantic 校验**：YAML 不合法时返回 422 + 具体错误位置，前端 Monaco 的波浪线标注对应行
- **自动创建操作记录**：每次 PUT 成功后写入 `operations` 表（`type='manual_edit'`），纳入 Undo/Redo 栈

**GET /api/scripts/{script_id}/diff?from=op_001&to=op_003**

```json
// Response 200 — 返回两个操作点之间的差异
{
    "code": 0,
    "data": {
        "from": { "id": "op_001", "created_at": "2026-06-05T10:00:00Z" },
        "to": { "id": "op_003", "created_at": "2026-06-05T12:00:00Z" },
        "patches": [
            { "op": "replace", "path": "/scenes/0/heading", "value": "内景. 图书馆 - 白天" },
            { "op": "add", "path": "/scenes/3", "value": { "scene_id": "S004" } }
        ]
    }
}
```

### 8.2 错误码规范

| 状态码 | 含义           | 示例场景                     |
| :----- | :------------- | :--------------------------- |
| 200    | 成功           | 正常返回                     |
| 400    | 客户端请求错误 | 上传内容为空、Patch 格式非法 |
| 404    | 资源不存在     | task_id 无效                 |
| 422    | 校验失败       | Pydantic 校验不通过          |
| 500    | 服务器内部错误 | LLM 调用失败、DB 连接异常    |
| 503    | 服务暂时不可用 | 模型 API 超时、系统过载      |

所有错误响应统一使用 `ErrorResponse` 模型：

```json
{
    "code": 422,
    "message": "脚本结构校验失败：scene_id 重复",
    "detail": "ValidationError: scenes[3].scene_id 'S001' already exists"
}
```

## 9. 前端架构设计

### 9.1 三栏布局模型

```mermaid
block-beta
    columns 3

    block:TopBar:3
        columns 3
        T1["Logo NovelScript"]
        T2["任务状态指示灯"]
        T3["导出 ▾ 按钮"]
    end

    block:Left:1
        columns 1
        L1["<b>左栏 (30%)</b>"]
        L2["TipTap 原文阅读器"]
        L3["· 段落折叠"]
        L4["· 锚点高亮"]
        L5["· 搜索定位"]
    end

    block:Center:1
        columns 1
        C1["<b>中栏 (40%)</b>"]
        C2["Monaco Editor"]
        C3["YAML / JSON 编辑"]
        C4["· 语法高亮"]
        C5["· 错误波浪线"]
        C6["· 代码折叠"]
    end

    block:Right:1
        columns 1
        R1["<b>右栏 (30%)</b>"]
        R2["┌─ Tab1 ─┬─ Tab2 ─┬ Tab3 ─┐<br>│ &emsp;预览&emsp; │ &emsp;图谱&emsp;  │ &emsp;AI&emsp;    │<br>└───────────────┘"]
        R3["Tab 内容区"]
    end

    block:BottomBar:3
        columns 2
        B1["进度条 ████████░░░░ 65%"]
        B2["系统日志滚动窗口"]
    end
```

- **面板宽度可拖拽调整**
- **右栏 Tab 切换**：Tab1 剧本可视化排版、Tab2 ReactFlow 知识图谱、Tab3 AI 对话与 Patch 历史

### 9.2 状态管理 (Zustand)

```typescript
// task-store.ts — 任务状态
interface TaskStore {
    taskId: string | null;
    novelId: string | null;
    status: TaskStatus;
    progress: number; // 0-100
    errorMessage: string | null;
    setTask: (taskId: string, novelId: string) => void;
    updateProgress: (p: number, status: string) => void;
}

// script-store.ts — 剧本数据
interface ScriptStore {
    yaml: string | null;
    fountain: string | null;
    scenes: Scene[];
    characters: Character[];
    sourceRefs: Map<string, SourceRef>; // element_id → source_ref
    highlightElement: (id: string) => void;
    highlightSource: (chapterId: string, offset: [number, number]) => void;
}

// editor-store.ts — 编辑器状态
interface EditorStore {
    undoStack: JsonPatch[];
    redoStack: JsonPatch[];
    activeTab: "preview" | "graph" | "chat";
    applyPatch: (patch: JsonPatch) => void;
    undo: () => void;
    redo: () => void;
}

// ui-store.ts — UI 状态
interface UIStore {
    leftPanelWidth: number; // 百分比
    centerPanelWidth: number;
    rightPanelWidth: number;
    setPanelWidths: (l: number, c: number, r: number) => void;
}
```

### 9.3 组件树与数据流

```mermaid
flowchart TD
    App["&lt;App/&gt;"]

    App --> TaskBar["&lt;TaskBar/&gt;<br/>📡 task-store<br/>(status, progress)"]
    App --> Layout["&lt;ThreePanelLayout/&gt;"]
    App --> StatusBar["&lt;StatusBar/&gt;<br/>📡 task-store<br/>(progress) + 系统日志"]

    Layout --> NovelReader["&lt;NovelReader/&gt;<br/>📡 script-store<br/>(highlightSource)"]
    Layout --> ScriptEditor["&lt;ScriptEditor/&gt;<br/>📡 script-store (yaml)<br/>+ editor-store (undo/redo)"]
    Layout --> RightPanel["&lt;RightPanel/&gt;"]

    RightPanel --> Preview["&lt;ScriptPreview/&gt;<br/>📡 script-store<br/>(highlightElement)"]
    RightPanel --> Graph["&lt;KnowledgeGraph/&gt;<br/>📡 script-store<br/>(characters, scenes)"]
    RightPanel --> Chat["&lt;AIChat/&gt;<br/>📡 task-store (taskId)"]
```

- **数据流**：单向 — 用户操作 → Zustand action → API 调用 → 更新 store → React 重渲染
- **SSE 订阅**：在 `NovelReader` 或 `TaskBar` 的 `useEffect` 中建立 `EventSource` 连接
- **溯源联动**：点击事件 → `script-store.highlightElement(id)` → 触发 `NovelReader` 滚动到对应 `offset`

### 9.4 双向溯源交互流程

```mermaid
flowchart TB
    subgraph A["👆 用户点击『右栏对白』"]
        direction TB
        A1["获取该 Element 的 source_ref"]
        A2["script-store 设置目标<br/>chapter_id + offset"]
        A3["NovelReader 滚动到对应段落<br/>+ 黄色高亮背景"]
        A1 --> A2 --> A3
    end

    subgraph B["👆 用户点击『左栏原文段落』"]
        direction TB
        B1["查询所有引用该 offset 的 Element"]
        B2["script-store 设置目标 element_ids"]
        B3["右栏 + 中栏高亮对应元素"]
        B1 --> B2 --> B3
    end
```

## 10. 部署设计

### 10.1 Docker Compose 编排

```yaml
# docker-compose.yml
version: "3.9"
services:
    db:
        image: pgvector/pgvector:pg18
        environment:
            POSTGRES_USER: novelscript
            POSTGRES_PASSWORD: ${DB_PASSWORD}
            POSTGRES_DB: novelscript
        volumes:
            - pgdata:/var/lib/postgresql/data
            - ./backend/app/db/init.sql:/docker-entrypoint-initdb.d/init.sql
        ports:
            - "5432:5432"

    backend:
        build: ./backend
        environment:
            DATABASE_URL: postgresql://novelscript:${DB_PASSWORD}@db:5432/novelscript
            DEEPSEEK_API_KEY: ${DEEPSEEK_API_KEY}
        depends_on:
            - db
        ports:
            - "8000:8000"

    frontend:
        build: ./frontend
        depends_on:
            - backend
        ports:
            - "5173:5173"

    nginx:
        image: nginx:alpine
        volumes:
            - ./nginx.conf:/etc/nginx/nginx.conf
        ports:
            - "80:80"
        depends_on:
            - backend
            - frontend

volumes:
    pgdata:
```

### 10.2 Nginx 反向代理

```nginx
server {
    listen 80;
    server_name novelscript.local;

    # 前端静态资源 + SSR
    location / {
        proxy_pass http://frontend:5173;
        proxy_set_header Host $host;
    }

    # 后端 API
    location /api/ {
        proxy_pass http://backend:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        # SSE 长连接
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 3600s;
    }

    # Swagger / ReDoc
    location /docs { proxy_pass http://backend:8000/docs; }
    location /redoc { proxy_pass http://backend:8000/redoc; }
    location /openapi.json { proxy_pass http://backend:8000/openapi.json; }
}
```

- **SSE 关键配置**：`proxy_buffering off; proxy_cache off;` 确保事件流不被 Nginx 缓冲

## 11. 测试设计

### 11.1 测试目标

验证长文本转换的连贯性、All-in-One 数据库的读写性能、AI 补丁应用的准确性及前端溯源交互的流畅度。

### 11.2 核心测试用例

| 编号      | 场景          | 操作步骤                                                  | 预期结果                                                                                  | 涉及模块                           |
| :-------- | :------------ | :-------------------------------------------------------- | :---------------------------------------------------------------------------------------- | :--------------------------------- |
| **TC-01** | 标准转换链路  | 上传《永恒至尊》前 4 章（约 1.5 万字），点击转换。        | 90秒内完成，生成合法 YAML，包含完整 Scene 与 Element，`source_ref` 准确。                 | Pipeline §3, Validator §3.5        |
| **TC-02** | 格式强校验    | 模拟 LLM 返回缺少引号的非法 JSON。                        | 后端捕获 `ValidationError`，自动触发重试修复，最终返回合法数据，日志记录修复过程。        | Auto-Fix Loop §3.5                 |
| **TC-03** | RAG 记忆检索  | 在第 4 章转换时，查询 `pgvector` 日志。                   | 系统成功检索到第 1 章的角色设定作为 Context 注入，角色性格未发生 OOC（崩塌）。            | RAG §7.2, pgvector DDL §5.5        |
| **TC-04** | 双向溯源      | 在右栏点击某句对白，观察左栏。                            | 左栏原文自动平滑滚动至对应段落，并添加黄色高亮背景。                                      | source_ref §5.4, 前端交互 §9.4     |
| **TC-05** | AI 补丁应用   | 在对话框输入"将第 1 场的地点改为赛博朋克酒吧"，点击应用。 | 后端生成 JSON Patch，更新 DB 中的 `script_json`，前端 YAML 与预览区同步刷新。             | Patch 模块 §7.4, 混合模型 §5.2     |
| **TC-06** | 撤销链 (Undo) | 连续应用 2 次 AI 补丁，点击"撤销"。                       | 剧本状态精准回退至上一版本，`operations` 表正确记录 `rollback` 类型日志。                 | 撤销/重做 §5.3, operations 表 §5.5 |
| **TC-07** | Fountain 导出 | 点击"导出 Fountain"，用记事本打开。                       | 格式符合 Fountain 语法规范（如 `INT. 地点 - 时间`，角色名大写居中），可被第三方工具解析。 | 导出模块 §7.5, YAML Schema §5.1    |
| **TC-08** | 异常输入防御  | 上传纯数字或空白文本。                                    | 前端拦截或后端返回 400 错误码及友好提示，服务不崩溃。                                     | 输入模块 §7.1, 错误码 §8.2         |

### 11.3 测试环境

- **样本数据**：使用网络小说《永恒至尊》（剑游太虚 著，前4章，约1.5万字）作为基准测试集，存储于 `.temp/novel_samples/`。
- **自动化**：使用 `pytest` 覆盖后端 API 与 Pydantic 校验逻辑；前端核心交互采用手动 E2E 验收。
- **关键断言**：
    - YAML 输出通过 Pydantic V2 模型校验（无 `ValidationError`）
    - `source_ref` 覆盖率 = 100%（每个 Element 非空）
    - Fountain 输出符合官方语法规范
    - Undo/Redo 操作栈在边界条件下（空栈 Redo、5 步上限回绕）行为正确

## 附录 A. 关键技术决策记录 (ADR)

| ID  | 决策                            | 理由                                                                                                                                                            | 替代方案                |
| :-- | :------------------------------ | :-------------------------------------------------------------------------------------------------------------------------------------------------------------- | :---------------------- |
| 1   | PostgreSQL All-in-One           | 72h 内降低运维心智负担，ACID 保证数据一致性                                                                                                                     | MySQL + FAISS + Neo4j   |
| 2   | YAML 快照 + JSON Patch 混合模型 | 兼顾高频编辑（低延迟 Patch）与安全回溯（快照锚点）                                                                                                              | 纯快照或纯增量          |
| 3   | Pydantic V2 强校验 + Auto-Fix   | 确保 LLM 不确定输出不污染数据层，闭环修复机制提升可靠性                                                                                                         | 不做校验或仅软提示      |
| 4   | 7 阶段管道 + 双模型路由            | 按任务类型匹配模型能力（Pro 用于 KG/优化，Flash 用于摘要/转换/对话），每阶段独立回退，最大化成本效益比                                                         | 全用 Pro 或全用 Flash   |
| 5   | SSE 进度推送                    | 轻量级单向数据流，比 WebSocket 实现更简单且对代理友好                                                                                                           | WebSocket / 轮询        |
| 6   | Zustand (4 stores)              | 轻量（<1KB）、无 boilerplate，4 个独立 store 避免单 store 膨胀                                                                                                  | Redux Toolkit / Context |
| 7   | 滑动窗口分片 (8000字阈值)       | 单次 LLM 调用 Token 可控，窗口重叠保证语义连续性                                                                                                                | 全文一次性送入          |
| 8   | 场景生成路由到 Flash（非 Pro）  | SRS 初版将"核心场景转换"分配给 Pro，但深度分析发现场景级转换是模式化生成任务，Flash 成本效益比更优（~10× 成本降低）。Pro 保留给最需推理的规划与一致性检查阶段。 | 严格按 SRS 分配 Pro     |

## 附录 B. 风险缓释

| 风险                             | 概率 | 影响 | 缓释策略                                                           |
| :------------------------------- | :--- | :--- | :----------------------------------------------------------------- |
| pgvector 环境配置受阻            | 中   | 高   | 降级为内存级 FAISS + JSON 文件存储，保核心业务                     |
| Pro 模型 API 不可用              | 低   | 中   | Flash 降级执行 Stage 1/3（质量下降但系统可用）                     |
| LLM 输出持续非法 (超出 2 次重试) | 低   | 中   | 降级返回已解析部分 + 警告标记，绝不崩溃                            |
| 72h 时间不足                     | 中   | 高   | P2 功能（URL 抓取、TTS、文生图）标记为视时间余量，优先保障核心管道 |
