# NovelScript (析幕) 软件需求规格说明书

- **项目名称**：NovelScript (析幕) – AI 驱动的长篇小说到结构化剧本转换系统
- **文档版本**：v2.0.0 (Release)
- **日期**：2026-06-05
- **作者**：Dinosaur_MC
- **开发约束**：单人 72 小时极限开发，预算 ￥500~2000
- **目标模型**：DeepSeek-v4-flash（轻量/对话） / DeepSeek-v4-pro（高质量转换/推理）
- **核心数据底座**：PostgreSQL 18+ (集成 pgvector 与 JSONB)

---

## 1. 引言

### 1.1 编写目的

本文档旨在完整、严谨地定义 NovelScript (析幕) 项目的功能需求、非功能需求、系统架构、数据模型与接口规范。本文档为 72 小时单人极限开发提供绝对清晰的实施蓝图，同时作为提交给七牛云 XEngineer 评审专家的核心技术白皮书，展现系统架构的完整性与工程落地的可行性。

### 1.2 项目背景

在网文 IP 影视化改编市场中，将数十万字的非结构化小说转化为符合视听语言逻辑的标准剧本，是一项极度耗时且依赖人工经验的工作。现有工具多局限于简单的格式排版，缺乏对故事因果结构、角色关系演进及场景调度的深度语义理解。
NovelScript 旨在利用大型语言模型（LLM）构建一条**高可用、带溯源、强校验的 AI 异步内容管线**，自动完成从小说文本到工业级结构化剧本（YAML/JSON/Fountain）的转换，并提供原文双向追溯、知识图谱可视化、AI 辅助协同编辑等功能，大幅降低 IP 改编门槛。

### 1.3 适用范围

- **输入**：3 章及以上中文/英文小说文本（支持文本粘贴、`.txt`/`.md` 文件上传、公开网页 URL 抓取）。
- **输出**：结构化剧本数据（YAML/JSON），以及兼容影视工业标准的 Fountain 纯文本标记格式。
- **目标用户**：网文作者、独立编剧、影视策划、内容平台开发者。
- **运行平台**：B/S 架构 Web 应用，现代浏览器访问。

### 1.4 术语与缩写

- **Scene（场景）**：剧本的基本叙事单元，对应一个连续时空内的情节段落。
- **Element（剧本元素）**：场景内部的原子单位，如对白（Dialogue）、动作（Action）、画面提示（Shot）等。
- **source_ref（溯源锚点）**：自定义增强字段，指向小说原文的章节与段落偏移量，用于双向追溯。
- **Fountain**：一种基于 Markdown 的纯文本剧本标记语言，可无缝导入 Final Draft 等专业软件。
- **pgvector**：PostgreSQL 的开源向量相似度搜索插件，用于替代独立的向量数据库（如 FAISS/Milvus）。
- **JSONB**：PostgreSQL 的二进制 JSON 数据类型，用于存储知识图谱与剧本结构，支持 GIN 索引与路径查询。

## 2. 总体描述

### 2.1 产品视角

NovelScript 是一个一体化的 Web 剧本工作台。用户输入小说文本后，系统通过多阶段 Pipeline（解析 -> 记忆构建 -> 并发转换 -> 强校验）生成剧本。前端提供“原文阅读-代码编辑-可视化预览”三栏协同界面，支持基于 RAG（检索增强生成）的上下文感知 AI 对话与剧本补丁（Patch）应用。

### 2.2 用户特征

- **小说作者**：关注 IP 转化效率，需要直观的原文对照与修改建议。
- **专业编剧**：关注场景划分合理性、对白张力及格式规范性，依赖 Fountain 格式导出至专业软件。
- **技术评委**：关注系统架构的鲁棒性、长文本处理的工程解法（并发/削峰/防幻觉）及数据一致性。

### 2.3 运行环境

- **前端**：React 19 + TypeScript + Vite，兼容 Chrome 90+, Edge 90+。
- **后端**：Python 3.13, FastAPI, Uvicorn, 运行于 Linux 容器环境。
- **数据库**：PostgreSQL 18 (搭载 `pgvector` 与 `uuid-ossp` 插件)。
- **网络**：需稳定访问 DeepSeek API，最低 2Mbps 带宽。

### 2.4 设计与实现约束

1.  **时间与人力**：单人 72 小时闭环开发。
2.  **技术栈锁定**：前端 React+TS，后端 FastAPI，数据库 PostgreSQL (All-in-One 架构)。
3.  **模型路由**：严格区分 DeepSeek-v4-pro（核心转换）与 DeepSeek-v4-flash（对话/摘要），以控制成本与延迟。
4.  **容错机制**：必须具备 LLM 结构化输出（JSON/YAML）的自动校验与重试修复机制。

### 2.5 资金使用计划 (预算 ￥2000)

- **模型 API 费用 (70%, ￥1400)**：保障 Pro 模型的高并发调用与 Flash 模型的长连接对话。
- **云服务器 (20%, ￥400)**：2C4G 轻量应用服务器，按量计费，用于部署 Docker 容器。
- **其他 (10%, ￥200)**：域名注册、SSL 证书、对象存储备用金、LLM开发Token费用。

### 2.6 假设与依赖

- 假设上传的小说文本包含可推断的章节边界（如“第X章”或明显的空行分隔）。
- 假设 DeepSeek API 在竞赛期间保持 99% 以上的可用性。
- 依赖开源社区提供的 `pgvector` 镜像与 React 生态组件。

## 3. 功能需求

### 3.1 小说输入模块

- **3.1.1 文本粘贴与上传**：支持 TipTap 富文本/Markdown 编辑器直接粘贴；支持 `.txt`/`.md` 文件上传（限制 5MB）。
- **3.1.2 网页抓取 (P1)**：输入 URL，后端通过 `BeautifulSoup`/`Playwright` 提取 `<article>` 或主内容区文本，自动清洗 HTML 标签。
- **3.1.3 章节智能切分**：后端使用正则（`第[零一二三四五六七八九十百千0-9]+章`）与 LLM 语义兜底进行切分。前端提供章节列表，允许用户手动合并、拆分或调整顺序。

### 3.2 LLM 预处理与记忆构建模块

- **3.2.1 全局摘要与图谱提取**：调用 Pro 模型提取故事梗概、角色列表（含性格/身份）、地点列表及角色关系网，构建全局知识图谱（JSONB 格式）。
- **3.2.2 向量化记忆入库 (RAG)**：将切分后的章节文本通过 Embedding 模型转化为向量，连同原文偏移量（Offset）存入 PostgreSQL 的 `pgvector` 字段，构建长文本记忆网络。

### 3.3 剧本转换引擎 (核心 Pipeline)

- **3.3.1 场景切分与重构**：以章为单位，结合全局知识图谱与 RAG 检索的前文记忆，调用 LLM 将叙事文本转换为场景序列（Scene）。
- **3.3.2 并发分块处理**：使用 `asyncio.Semaphore` 控制并发，单章超过 8000 字时自动滑动窗口分片。通过 SSE (Server-Sent Events) 向前端推送实时进度。
- **3.3.3 强校验与自动修复**：使用 Pydantic V2 校验 LLM 输出的 JSON。若抛出 `ValidationError`，系统自动捕获错误信息，构造“修复 Prompt”要求 LLM 重新输出，最大重试 2 次。
- **3.3.4 溯源锚点注入**：为每个剧本 Element 强制注入 `source_ref`（包含 `chapter_id` 与 `offset`），确保 100% 可追溯。

### 3.4 输出与导出

- **3.4.1 多格式生成**：
    - **YAML/JSON**：供系统内部读取与前端渲染。
    - **Fountain**：将结构化数据序列化为标准 Fountain 纯文本语法，支持一键下载 `.fountain` 文件。
- **3.4.2 元数据注入**：在文件头部自动注入转换时间、使用模型、原著信息等 Metadata。

### 3.5 剧本预览与交互工作台

- **3.5.1 三栏协同布局**：
    - **左栏**：小说原文阅读器（支持段落高亮与锚点定位）。
    - **中栏**：Monaco Editor（YAML/JSON 代码编辑）或 Fountain 源码编辑。
    - **右栏**：剧本可视化预览（模拟影视排版）与知识图谱力导向图。
- **3.5.2 双向溯源跳转**：点击右栏任意对白/动作，左栏原文自动滚动至对应段落并高亮；反之亦然。
- **3.5.3 图谱联动**：在知识图谱中点击某角色，剧本预览区自动高亮该角色所有出场场景与对白。

### 3.6 AI 辅助编辑与对话模块

- **3.6.1 上下文感知对话**：右侧面板集成 AI 助手。用户提问时，系统自动将当前选中的 Scene、相关角色设定及原文片段注入 Prompt（基于 Flash 模型）。
- **3.6.2 结构化补丁 (Patch) 生成**：AI 可生成符合 JSON Patch 规范的修改建议（如修改地点、增加对白）。
- **3.6.3 一键应用与撤销链 (Undo)**：用户确认应用 Patch 后，前端实时更新视图，后端记录操作日志。支持最多 5 步的 Undo/Redo 历史回滚。

### 3.7 扩展功能 (P2, 视时间余量)

- **TTS 语音演示**：调用浏览器 Web Speech API 或第三方接口，根据剧本中的情绪提示（Parenthetical）朗读对白。
- **AI 场景概念图**：根据 Scene 的 `action_description` 调用文生图 API 生成场景气氛图。

## 4. 非功能需求

### 4.1 性能指标

- **转换延迟**：3 章（约 2 万字）小说的端到端转换时间 ≤ 90 秒（依赖并发与模型响应）。
- **首屏加载**：前端 Gzip 压缩后资源 ≤ 2MB，首次加载时间 ≤ 3 秒。
- **并发支持**：系统架构支持至少 10 个独立任务队列并行处理，互不阻塞。

### 4.2 可靠性与鲁棒性

- **格式兜底**：LLM 输出非法 JSON 时，100% 触发自动修复流程；若 2 次重试仍失败，降级返回已解析的部分场景并警告用户，系统绝不崩溃。
- **断点续传**：转换过程中若遇网络波动，支持从失败的 Chunk 处恢复，而非全盘重跑。

### 4.3 安全性

- **凭证隔离**：所有 API Key 仅存于后端 `.env`，严禁硬编码或暴露给前端。
- **XSS 防护**：前端渲染小说原文与 AI 回复时，强制使用 `DOMPurify` 进行 HTML 消毒。
- **数据隐私**：提供“阅后即焚”选项，任务完成 24 小时后自动清理服务器临时文件与向量数据。

### 4.4 可维护性与部署

- **容器化**：提供完整的 `docker-compose.yml`，一键拉起 Frontend, Backend, PostgreSQL。
- **API 文档**：FastAPI 自动生成 Swagger UI (`/docs`) 与 ReDoc。

## 5. 系统架构

### 5.1 总体架构 (All-in-One PostgreSQL)

系统摒弃了传统的“MySQL + FAISS + Neo4j”多组件堆砌方案，采用 **PostgreSQL 作为唯一数据底座**，极大降低了 72 小时内的运维心智负担与网络通信开销。

```text
[Browser: React 19 + TS + Ant Design + TipTap/Monaco]
      | (HTTP/REST & SSE)
      v
[Nginx Reverse Proxy & Static Server]
      |
      v
[FastAPI Application Server (Python 3.13)]
      ├─ /api/novel/*      (任务调度与状态机)
      ├─ /api/editor/*     (AI 对话与 Patch 应用)
      ├─ LLM Router        (DeepSeek Pro/Flash 智能路由)
      └─ Data Access Layer (Asyncpg + SQLModel)
             |
             v
[PostgreSQL 18 (All-in-One Data Hub)]
      ├─ 关系数据 (tasks, operations, dialogues)
      ├─ 向量数据 (chapters.embedding via pgvector) -> 替代 FAISS
      └─ 图/文档数据 (JSONB via GIN Index)          -> 替代 Neo4j/MongoDB
```

### 5.2 前端架构

- **框架**：React 19 + TypeScript + Vite。
- **路由**：React Router v7
- **状态管理**：Zustand (轻量级) 或 React Context + useReducer。
- **UI 组件**：Ant Design 6 (基础组件), Monaco Editor (代码编辑), TipTap (富文本), ReactFlow (知识图谱)。

### 5.3 后端架构

- **Web 框架**：FastAPI (异步非阻塞)。
- **ORM/DB Driver**：SQLModel + `asyncpg` (高性能异步 PgSQL 驱动)。
- **AI 编排**：LangChain (Prompt 管理), `pgvector` (相似度检索)。
- **并发控制**：`asyncio.gather` + `Semaphore`。

## 6. 数据设计

### 6.1 核心数据结构：YAML Schema (完整版)

```yaml
script:
  meta:
    title: "星辰低语"
    author: "原著: XXX / 改编: NovelScript AI"
    model: "deepseek-v4-pro"
    timestamp: "2026-06-05T12:00:00Z"
    version: "1.0.0"
  summary: "在废弃的星际飞船上，颓废的领航员林明与冷酷的仿生人艾娃展开了一场关于宇宙边缘与人类情感的对话。"
  characters:
    - id: "char_01"
      name: "林明"
      description: "30岁，颓废的星际领航员，右眼有机械义眼。"
    - id: "char_02"
      name: "艾娃"
      description: "AI 仿生人，冷静，缺乏人类情感。"
  scenes:
    - scene_id: "S001"
      heading: "内景. 废弃飞船驾驶舱 - 夜晚"
      location: "飞船驾驶舱"
      time_of_day: "夜晚"
      characters_present: ["char_01", "char_02"]
      elements:
        - type: "action"
          content: "控制台上闪烁着微弱的红光。林明疲惫地靠在座椅上，手里把玩着一个旧式怀表。艾娃静静地站在他身后。"
          source_ref:
            chapter_id: "ch_02"
            offset: [1450, 1520]
        - type: "dialogue"
          character_id: "char_01"
          parenthetical: "(自嘲地笑)"
          line: "你说，宇宙的边缘到底有什么？"
          source_ref:
            chapter_id: "ch_02"
            offset: [1521, 1545]
        - type: "dialogue"
          character_id: "char_02"
          parenthetical: "(机械音，毫无波澜)"
          line: "根据目前的物理模型，只有无尽的真空和辐射。"
          source_ref:
            chapter_id: "ch_02"
            offset: [1546, 1580]
  knowledge_graph:
    nodes:
      - id: "char_01", label: "林明", type: "character"
      - id: "char_02", label: "艾娃", type: "character"
    edges:
      - source: "char_01", target: "char_02", relation: "主仆/同伴", weight: 0.8
```

### 6.2 战略输出格式：Fountain 示例

```fountain
Title: 星辰低语
Author: 原著: XXX / 改编: NovelScript AI
Draft date: 2026-06-05

INT. 废弃飞船驾驶舱 - 夜晚

控制台上闪烁着微弱的红光。林明疲惫地靠在座椅上，手里把玩着一个旧式怀表。艾娃静静地站在他身后。

林明
(自嘲地笑)
你说，宇宙的边缘到底有什么？

艾娃
(机械音，毫无波澜)
根据目前的物理模型，只有无尽的真空和辐射。
```

### 6.3 任务状态模型 (Pydantic V2)

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
    status: TaskStatus
    progress: int = Field(ge=0, le=100)
    summary: Optional[str] = None
    characters: Optional[List[Dict[str, Any]]] = None
    script_yaml: Optional[str] = None
    script_fountain: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime
```

### 6.4 持久化存储结构 (PostgreSQL DDL 完整版)

利用 `pgvector` 和 `JSONB` 实现 All-in-One 架构。

```sql
-- 启用必要插件
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 1. 任务主表 (利用 JSONB 存储复杂图谱与剧本结构)
CREATE TABLE tasks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_text TEXT NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    progress INT DEFAULT 0,
    summary TEXT,
    characters_json JSONB,
    knowledge_graph JSONB,
    script_yaml TEXT,
    script_json JSONB,
    script_fountain TEXT,
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_tasks_status ON tasks(status);

-- 2. 章节与向量块表 (完美替代 FAISS，支持 RAG 检索)
CREATE TABLE chapters (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id UUID REFERENCES tasks(id) ON DELETE CASCADE,
    chapter_index INT NOT NULL,
    title VARCHAR(255),
    content TEXT NOT NULL,
    -- 核心：存储文本的向量表示，用于长文本记忆网络
    embedding vector(1536),
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
-- 创建 HNSW 索引加速余弦相似度检索 (KNN)
CREATE INDEX ON chapters USING hnsw (embedding vector_cosine_ops);
CREATE INDEX idx_chapters_task ON chapters(task_id, chapter_index);

-- 3. 操作日志表 (支持 JSONB 差异对比与 Undo 链)
CREATE TABLE operations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id UUID REFERENCES tasks(id) ON DELETE CASCADE,
    type VARCHAR(50) NOT NULL, -- 'manual_edit', 'ai_patch', 'rollback'
    target_path TEXT,          -- 例如 'scenes[0].elements[1].line'
    diff_json JSONB,           -- 记录补丁
    previous_snapshot JSONB,   -- 修改前的 JSONB 快照
    applied BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_ops_task_time ON operations(task_id, created_at DESC);

-- 4. AI 对话记录表
CREATE TABLE dialogues (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id UUID REFERENCES tasks(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL, -- 'user', 'assistant'
    content TEXT NOT NULL,
    patch_json JSONB,          -- 若消息包含补丁则记录
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_dialog_task_time ON dialogues(task_id, created_at);
```

## 7. 接口需求

### 7.1 RESTful API 核心端点

- `POST /api/novel/upload`
    - **Body**: `multipart/form-data` (file) 或 `application/json` (content)
    - **Response**: `{ "task_id": "uuid", "chapters": [{"index": 1, "title": "第一章"}] }`
- `POST /api/novel/preprocess/{task_id}`
    - **Body**: `{ "chapter_boundaries": [...] }` (可选)
    - **Response**: `{ "status": "preprocessing" }`
- `GET /api/novel/status/{task_id}` (支持 SSE 流式返回进度)
    - **Response**: `TaskResponse` 模型
- `POST /api/novel/convert/{task_id}`
    - **Response**: `{ "status": "converting" }`
- `POST /api/novel/resume/{task_id}`
    - **Description**: 断点续传。转换过程中若遇网络波动或 LLM 调用失败，从上次成功的 Chunk 处恢复，避免全盘重跑。
    - **Response**: `{ "status": "converting", "resumed_from_chunk": 3 }`
- `GET /api/novel/export/{task_id}?format=fountain`
    - **Response**: 文件流 (`.fountain` 或 `.yaml`)

### 7.2 AI 编辑与对话接口

- `POST /api/editor/chat/{task_id}`
    - **Body**: `{ "message": "把第2场的地点改为图书馆", "scene_id": "S002" }`
    - **Response**: `{ "reply": "好的...", "patch": { "op": "replace", "path": "/scenes/1/location", "value": "图书馆" } }`
- `POST /api/editor/apply_patch/{task_id}`
    - **Body**: `{ "patch": {...} }`
    - **Response**: `{ "success": true, "updated_yaml": "..." }`
- `POST /api/editor/undo/{task_id}`
    - **Response**: 回滚后的完整剧本数据。

## 8. 项目计划（72 小时极限排期）

| 阶段                  | 时间分配 | 核心任务                                                                                                                                              | 交付产出                                           |
| :-------------------- | :------- | :---------------------------------------------------------------------------------------------------------------------------------------------------- | :------------------------------------------------- |
| **D0: 基建与骨架**    | 0-8h     | 1. 搭建 React+Vite 与 FastAPI 脚手架。<br>2. 编写 PostgreSQL DDL 与 Docker Compose。<br>3. 实现文本上传、正则切分与 DB 持久化。                       | 跑通上传接口，数据库成功落库，前端可展示章节列表。 |
| **D1: 核心引擎**      | 8-20h    | 1. 实现 LangChain 预处理链（摘要/图谱）。<br>2. 实现 `pgvector` 向量化入库。<br>3. 编写并发转换引擎与 Pydantic 强校验/重试机制。                      | 后端能稳定输出 3 章样本的合法 YAML/JSON，无崩溃。  |
| **D2: 前端与交互**    | 20-44h   | 1. 搭建三栏布局（TipTap/Monaco/预览）。<br>2. 实现 `source_ref` 双向溯源高亮联动。<br>3. 集成 ReactFlow 渲染知识图谱。<br>4. 实现 Fountain 导出逻辑。 | 完整可交互的 Web 工作台，支持导出 `.fountain`。    |
| **D3: AI 编辑与打磨** | 44-60h   | 1. 实现 AI 对话面板与 Patch 生成逻辑。<br>2. 实现 Undo/Redo 操作日志链。<br>3. 全局异常捕获与 UI 错误提示优化。                                       | AI 辅助编辑功能可用，系统具备极高鲁棒性。          |
| **D4: 交付与路演**    | 60-72h   | 1. 撰写 YAML Schema 设计白皮书。<br>2. 录制 3 分钟高质量 Demo 视频。<br>3. 部署至云服务器，配置 Nginx 与域名。                                        | 公网可访问的 Demo 链接、完整源码、路演 PPT。       |

**风险缓释策略**：

- 若 `pgvector` 环境配置受阻，D1 立即降级为内存级 `FAISS` + `JSON` 文件存储，保核心业务。
- 若 AI 对话 Patch 生成不稳定，D3 降级为“仅提供修改建议文本，由用户手动在中栏修改 YAML”。

## 9. 测试方案

### 9.1 测试目标

验证长文本转换的连贯性、All-in-One 数据库的读写性能、AI 补丁应用的准确性及前端溯源交互的流畅度。

### 9.2 核心测试用例 (Test Cases)

| 编号      | 场景          | 操作步骤                                                  | 预期结果                                                                                  |
| :-------- | :------------ | :-------------------------------------------------------- | :---------------------------------------------------------------------------------------- |
| **TC-01** | 标准转换链路  | 上传《永恒至尊》前 4 章（约 1.5 万字），点击转换。       | 90秒内完成，生成合法 YAML，包含完整 Scene 与 Element，`source_ref` 准确。                 |
| **TC-02** | 格式强校验    | 模拟 LLM 返回缺少引号的非法 JSON。                        | 后端捕获 `ValidationError`，自动触发重试修复，最终返回合法数据，日志记录修复过程。        |
| **TC-03** | RAG 记忆检索  | 在第 4 章转换时，查询 `pgvector` 日志。                   | 系统成功检索到第 1 章的角色设定作为 Context 注入，角色性格未发生 OOC（崩塌）。            |
| **TC-04** | 双向溯源      | 在右栏点击某句对白，观察左栏。                            | 左栏原文自动平滑滚动至对应段落，并添加黄色高亮背景。                                      |
| **TC-05** | AI 补丁应用   | 在对话框输入“将第 1 场的地点改为赛博朋克酒吧”，点击应用。 | 后端生成 JSON Patch，更新 DB 中的 `script_json`，前端 YAML 与预览区同步刷新。             |
| **TC-06** | 撤销链 (Undo) | 连续应用 2 次 AI 补丁，点击“撤销”。                       | 剧本状态精准回退至上一版本，`operations` 表正确记录 `rollback` 类型日志。                 |
| **TC-07** | Fountain 导出 | 点击“导出 Fountain”，用记事本打开。                       | 格式符合 Fountain 语法规范（如 `INT. 地点 - 时间`，角色名大写居中），可被第三方工具解析。 |
| **TC-08** | 异常输入防御  | 上传纯数字或空白文本。                                    | 前端拦截或后端返回 400 错误码及友好提示，服务不崩溃。                                     |

### 9.3 测试环境

- **样本数据**：使用网络小说《永恒至尊》（剑游太虚 著，前4章，约1.5万字）作为基准测试集，存储于 `.temp/novel_samples/`。
- **自动化**：使用 `pytest` 覆盖后端 API 与 Pydantic 校验逻辑；前端核心交互采用手动 E2E 验收。

## 10. 附录

### 10.1 模型路由与成本控制策略

- **DeepSeek-v4-pro**：仅用于“全局知识图谱抽取”与“核心场景转换”。预估单次完整转换消耗约 20K Tokens，成本约 ￥0.08。
- **DeepSeek-v4-flash**：用于“章节切分”、“AI 对话”、“轻量补丁生成”。预估单次对话消耗约 2K Tokens，成本极低。
- **预算评估**：￥1400 预算足以支撑约 10,000 次完整转换与海量对话测试，完全满足 72 小时开发、调试与路演需求。

### 10.2 用户界面原型 (文字描述)

- **顶栏**：Logo (NovelScript), 任务状态指示灯, 导出下拉菜单 (YAML/JSON/Fountain)。
- **左栏 (30%)**：TipTap 原文阅读器，支持段落折叠与高亮。
- **中栏 (40%)**：Monaco Editor，支持 YAML 语法高亮、折叠、错误波浪线提示。
- **右栏 (30%)**：Tab 切换面板。Tab 1: 剧本可视化排版；Tab 2: ReactFlow 知识图谱；Tab 3: AI 对话与 Patch 历史。
- **底栏**：全局进度条与系统日志滚动窗口。

### 10.3 参考标准与文献

1.  **Fountain Syntax**: 纯文本剧本标记语言官方规范。
2.  **Final Draft (.fdx)**: 影视工业标准 XML 结构参考。
3.  **pgvector Documentation**: PostgreSQL 向量检索插件官方文档。
4.  **《从文本到影像蓝图：NovelScript 项目可行性深度评估》**: 内部战略指导文档。
