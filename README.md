<p align="center">
  <h1 align="center">🎬 NovelScript (析幕)</h1>
  <p align="center">
    <strong>AI 驱动的长篇小说到结构化剧本转换系统</strong><br>
    <em>An AI-driven conversion system from long-form novels to structured scripts.</em>
  </p>
  <p align="center">
    <img src="https://img.shields.io/badge/Python-3.13-blue?logo=python" alt="Python">
    <img src="https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white" alt="FastAPI">
    <img src="https://img.shields.io/badge/Celery-37814A?logo=celery&logoColor=white" alt="Celery">
    <img src="https://img.shields.io/badge/LangChain-🦜️🔗-1C3C3C" alt="LangChain">
    <img src="https://img.shields.io/badge/PostgreSQL-pgvector-336791?logo=postgresql&logoColor=white" alt="PostgreSQL">
    <img src="https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black" alt="React">
    <img src="https://img.shields.io/badge/License-GPL%20v3-green" alt="License">
  </p>
</p>

## 📖 项目简介 (Overview)

**NovelScript (析幕)** 是一款面向网文 IP 影视化改编市场的企业级 AI 内容管线系统。

在传统的 IP 改编中，将数十万字的非结构化小说转化为符合视听语言逻辑的标准剧本，是一项极度耗时且依赖人工经验的工作。市面上的工具多局限于简单的格式排版，缺乏对故事因果结构、角色关系演进及场景调度的深度语义理解。

NovelScript 摒弃了“一个 Prompt 搞定一切”的玩具思维，构建了一条**高可用、带溯源、强校验的异步 AI 内容管线**。它能够将 3 章以上的长篇小说，精准转化为符合影视工业标准（兼容 Fountain 语法）的结构化剧本，并提供**原文双向追溯**、**知识图谱可视化**与 **AI 辅助协同编辑**功能，大幅降低 IP 改编门槛。

> 💡 **核心理念**：大模型的输出是概率性的，但工业管线必须是确定性的。我们用工程的严谨（强校验/All-in-One DB/并发削峰），锁定 AI 的创造力。

## ✨ 核心特性 (Core Features)

### 🚀 1. 工业级双模型路由与并发管线

- **智能路由**：严格区分 `DeepSeek-v4-pro`（负责高难度的核心场景转换与图谱抽取）与 `DeepSeek-v4-flash`（负责轻量摘要、对话与补丁生成），在保证质量的同时极致压缩 Token 成本。
- **7 阶段智能管线**：Chunking → Summarize → RAG → GraphRAG → Conversion → Optimization → Narrative Summary。每阶段独立回退，段落级切分杜绝裸截断。

### 🛡️ 2. 应用层重试与 Pydantic V2 强校验

- 彻底解决 LLM 结构化输出（JSON）的"格式漂移"痛点。
- 独创 **指数退避重试**：每阶段可配置 (1-3 次)，处理网络错误、超时、限流、5xx。不可重试的 4xx 直接上抛。
- `JsonOutputParser` + `model_validate()` 双阶段校验，各级独立回退——系统绝不崩溃。

### 🔗 3. 双向溯源映射 (Trace Mapping)

- 剧本中的每一个元素（对白/动作）均强制注入 `source_ref` 锚点（包含 `chapter_id` 与 `offset`）。
- 在前端 Web IDE 中，点击任意剧本台词，左侧原文阅读器自动平滑滚动至对应段落并高亮，确保 AI 改编的**绝对可审计性**。

### 🗄️ 4. All-in-One PostgreSQL 极简架构

- **拒绝组件堆砌**：摒弃了传统的 `MySQL + FAISS + Neo4j` 臃肿架构。
- 利用 **PostgreSQL 18+** 作为唯一数据底座：
    - 使用 `pgvector` 插件替代独立向量数据库，在库内直接完成 HNSW 索引与 KNN 检索，构建长文本 RAG 记忆网络。
    - 使用 `JSONB` 与 `JSONPath` 替代图数据库，轻量级存储与查询角色关系知识图谱。
    - 保证了事务的 ACID 特性，让 72 小时内的 Docker 编排与运维心智负担降至最低。

### 🎬 5. 无缝对接影视工业 (Fountain 战略支点)

- 除了输出供系统读取的 YAML/JSON，更支持一键导出 **Fountain** 纯文本标记格式。
- 打破 AI 工具与传统影视工业的壁垒，生成的 `.fountain` 文件可直接导入 Final Draft、Celtx 等专业编剧软件，具备直接投入商业生产的价值。

## 🏗️ 系统架构 (Architecture)

系统采用**前后端分离 + Celery 异步任务队列 + All-in-One 数据底座**的微服务架构。

```mermaid
graph TD
    subgraph 前端工作台["前端工作台 (React 19 + TypeScript)"]
        A[TipTap 原文阅读器]
        B[Monaco YAML 编辑器]
        C[剧本可视化预览 / ReactFlow 知识图谱]
        D[AI 对话面板]

        A <-->|双向溯源| B
        B <-->|实时渲染| C
        D <-->|联动| C
    end

    subgraph 后端引擎["后端引擎 (FastAPI + Celery)"]
        E[RESTful API (SSE 进度推送)]
        F[LLM Router (Pro ↔ Flash)]
        G[8-Stage Pipeline:<br/>Chunking → Summarize → RAG →<br/>GraphRAG → Conversion →<br/>Post-Processing → Optimize → Narrative Summary]
        H[Celery Worker (Redis broker)]
    end

    subgraph 数据底座["数据底座 (PostgreSQL 18 All-in-One)"]
        I[(关系数据: users, novels, tasks)]
        J[(向量数据: pgvector HNSW)]
        K[(图数据: knowledge_nodes + knowledge_edges)]
    end

    subgraph 中间件["消息与缓存 (Redis 7)"]
        L[(Celery Broker + Result Backend)]
        M[(JWT 黑名单 + 限流 + 用户缓存)]
    end

    A -->|REST + SSE| E
    B -->|REST| E
    C -->|REST| E
    D -->|SSE| E
    E --> F
    F --> G
    E -->|apply_async()| H
    H -->|update_state()| L
    E -->|SSE poll| L
    E --> I
    E --> J
    E --> K
    G --> I
    G --> J
    G --> K
    H --> I
    H --> J
    H --> K
```

## 🛠️ 技术栈 (Tech Stack)

| 领域        | 技术选型                                                                   | 说明                                 |
| :---------- | :------------------------------------------------------------------------- | :----------------------------------- |
| **前端**    | React 19, TypeScript, Vite, React Router v7, Ant Design 6, TipTap, Monaco Editor, @xyflow/react, Zustand | Web IDE 三栏协同编辑体验 (SSR + API proxy) |
| **后端**    | Python 3.13, FastAPI (sync psycopg2), Pydantic V2/SQLModel, Uvicorn        | 同步数据层 + 异步管道引擎并行        |
| **AI 编排** | LangChain / LangGraph, DeepSeek API (v4-pro / v4-flash), OpenRouter (embeddings) | 双模型路由，应用层重试，上下文预算感知 |
| **任务队列**| Celery + Redis 7                                               | 异步 Pipeline 执行，SSE 进度推送 (AsyncResult 轮询) |
| **数据库**  | PostgreSQL 18 (`pgvector` HNSW, `pg_trgm` GIN, `uuid-ossp`)   | All-in-One: 关系 + 向量 + 图 (JSONB + 点边表) |
| **部署**    | Docker, Docker Compose (5 services: db, redis, api, worker, frontend) | 一键编排，仅前端端口 (3000) 暴露 |

## 🚀 快速开始 (Quick Start)

只需 3 步，即可在本地拉起完整的 NovelScript 服务。

### 1. 环境准备

确保你的机器已安装 [Docker](https://www.docker.com/) 和 [Docker Compose](https://docs.docker.com/compose/)。

### 2. 配置环境变量

克隆仓库并配置你的大模型 API Key：

```bash
git clone https://github.com/your-username/NovelScript.git
cd NovelScript
cp backend/.env.example backend/.env
# 编辑 backend/.env，填入 DEEPSEEK_API_KEY 和 OPENROUTER_API_KEY
```

### 3. 一键启动

```bash
# 生产模式（仅前端端口暴露）
docker compose up -d --build

# 开发模式（暴露所有后端端口用于调试）
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
```

- **前端工作台**：访问 [http://localhost:3000](http://localhost:3000)
- **后端 API（仅开发模式）**：访问 [http://localhost:8000/docs](http://localhost:8000/docs)

## 📂 项目结构 (Project Structure)

```text
NovelScript/
├── docker-compose.yml          # 生产编排 (5 services, 内部网络，仅前端 :3000)
├── docker-compose.dev.yml      # 开发覆盖 (额外暴露 DB:5432, Redis:6379, API:8000)
│
├── backend/                    # 🐍 FastAPI + Celery Worker
│   ├── app/
│   │   ├── api/v1/             # 25 RESTful 端点 (auth, novels, scripts, tasks, editor)
│   │   ├── core/               # 配置, JWT, DB 连接, Redis, Celery App
│   │   ├── models/             # Pydantic V2 + SQLModel (9 表)
│   │   ├── services/           # BaseCRUD, DB 缓存, 限流, 黑名单, 用户缓存
│   │   ├── tasks/              # Celery 后台任务 (run_pipeline)
│   │   └── db/                 # DDL (init.sql), 连接工具
│   ├── cli/                    # Pipeline 引擎 (8 阶段, 16 文件)
│   ├── tests/                  # 288 测试 (5 目录, 27 文件)
│   ├── Dockerfile              # 多阶段 (api + worker targets)
│   └── pyproject.toml
│
├── frontend/                   # ⚛️ React 19 + React Router v7 (SSR)
│   ├── app/
│   │   ├── api/                # API 客户端 (6 模块)
│   │   ├── components/         # UI 组件 (11 文件, 含 TipTap/Monaco/ReactFlow)
│   │   ├── hooks/              # 自定义 Hooks (6 个)
│   │   ├── routes/             # 路由页面 (4 个)
│   │   └── stores/             # Zustand 状态管理 (6 stores)
│   ├── Dockerfile
│   └── package.json
│
├── docs/                       # 📄 架构文档与设计说明书
│   ├── business-logic.md       # 完整 API 参考 + 活动图 + 状态机
│   ├── SRS 需求规格说明书.md
│   ├── SDS 软件设计说明书.md
│   ├── YAML_Schema_设计说明.md
│   └── dev_references.md
│
└── reports/                    # 📊 行业报告 (PDF)
```

## 🗺️ 演进路线 (Roadmap)

- [x] **Phase 1: 核心管线与 All-in-One 架构 (Current)**
    - 跑通小说到 YAML/Fountain 的转换闭环。
    - 实现 pgvector RAG 记忆网络与 Pydantic Auto-Fix。
- [ ] **Phase 2: 多模态扩展 (Next)**
    - 接入 TTS API，根据剧本情绪提示（Parenthetical）自动生成角色配音。
    - 接入文生图模型，根据 Scene Action 生成场景概念气氛图。
- [ ] **Phase 3: SaaS 化与协同**
    - 引入 WebSocket 实现多人实时协同编辑剧本。
    - 构建针对“剧本戏剧张力”的自动化 LLM 评估基准（Evaluation Framework）。

## 📄 许可证 (License)

本项目基于 [GPL v3 License](LICENSE) 开源。

---

<p align="center">
  <strong>Built with ❤️ and ☕ by Dinosaur_MC for Qiniu XEngineer 2026.</strong>
</p>
