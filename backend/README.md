# NovelScript Backend

NovelScript (析幕) 后端 API 服务 — AI 驱动的长篇小说到结构化剧本转换系统。

## 技术栈

| 类别        | 选型                       |
| ----------- | -------------------------- |
| 语言        | Python 3.13                |
| Web 框架    | FastAPI (异步)             |
| ASGI 服务器 | Uvicorn                    |
| 数据校验    | Pydantic V2                |
| ORM         | SQLModel + asyncpg         |
| AI 编排     | LangChain + LangGraph      |
| 向量检索    | pgvector                   |
| 并发控制    | asyncio.gather + Semaphore |
| 实时推送    | SSE (sse-starlette)        |
| 网页抓取    | BeautifulSoup4             |

## 快速开始

```bash
# 安装依赖
uv sync

# 开发模式
uv run --active main.py

# 生产模式
uv run --active uvicorn app.main:app --host 0.0.0.0 --port 8000
```

- API 文档 (Swagger): `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
- 健康检查: `http://localhost:8000/health`

## Docker 部署

```bash
docker build -t novelscript-backend .
docker run -p 8000:8000 --env-file .env novelscript-backend
```

## 项目结构

```text
backend/
├── main.py                  # 入口: 加载环境变量, 启动 Uvicorn
├── pyproject.toml           # 项目配置与依赖声明
├── app/
│   ├── main.py              # FastAPI 应用实例, 中间件, 异常处理, 路由注册
│   ├── api/                 # RESTful 路由 (SSE 进度推送)
│   │   └── v1.py            # /api/v1/* 端点
│   ├── core/                # 配置, 安全, 数据库连接
│   ├── models/              # Pydantic V2 数据模型 (Task, Scene, Script)
│   │   └── http.py          # 基础请求/响应模型
│   ├── services/            # 核心业务: LLM Router, RAG, Pipeline, Auto-Fix
│   └── db/                  # PostgreSQL DDL, 初始化脚本
└── tests/                   # pytest 测试用例
```

## 核心 Pipeline

```
上传 → 章节切分 → 预处理(摘要/图谱) → 向量化入库(RAG)
                                              ↓
导出(Fountain/YAML) ← 强校验/Auto-Fix ← 并发转换 ← LLM Router(Pro/Flash)
```

## 环境变量

将 `.env.example` 复制为 `.env` 并填写:

| 变量               | 说明                                           |
| ------------------ | ---------------------------------------------- |
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥                              |
| `DATABASE_URL`     | PostgreSQL 连接串 (`postgresql+asyncpg://...`) |
| `DEBUG`            | 调试模式 (`true`/`false`)                      |
