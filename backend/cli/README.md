# NovelScript CLI — Pipeline Engine Reference

将长篇小说自动转换为结构化剧本的命令行工具。

## 目录

- [快速开始](#快速开始)
- [命令行参数](#命令行参数)
- [环境变量](#环境变量)
- [Pipeline 流程](#pipeline-流程)
- [输出格式](#输出格式)
- [双向溯源](#双向溯源)
- [LLM 架构](#llm-架构)
- [错误处理与重试](#错误处理与重试)
- [示例](#示例)
- [模块索引](#模块索引)

## 快速开始

```bash
# 前置：配置 API Key
cp backend/.env.example backend/.env
# 编辑 backend/.env，填入 DEEPSEEK_API_KEY 和 OPENROUTER_API_KEY

# 单文件输入（自动切分章节）
uv run python -m cli.pipeline novel.txt -o output.yaml

# 目录输入（每个 .txt / .md 文件为一个章节，跳过切分）
uv run python -m cli.pipeline chapters/ -o output.yaml

# 仅处理前 3 章 + 调整并发
uv run python -m cli.pipeline chapters/ -n 3 -c 10 -o output.yaml

# JSON 输出
uv run python -m cli.pipeline novel.txt --json -o output.json
```

## 命令行参数

```
uv run python -m cli.pipeline <INPUT> [选项]
```

### 位置参数

| 参数 | 说明 |
|------|------|
| `INPUT` | 输入路径。可以是单个 `.txt` 文件或包含 `.txt`/`.md`/`.utf8` 文件的目录。目录模式下每个文件按字母顺序视为一个独立章节。 |

### 可选参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `-o`, `--output OUTPUT` | `str` | stdout | 结果写入文件（不在终端打印） |
| `--json` | flag | — | 输出 JSON 格式（默认 YAML） |
| `-n N`, `--limit N` | `int` | 全部 | 仅处理前 N 个章节 |
| `-c C`, `--concurrency C` | `int` | 20 | 最大并发 LLM API 调用数 |
| `-s STYLE`, `--style STYLE` | `str` | 空 | AI 编剧指示，注入到转换与优化 prompt 中 |

### 并发控制

`-c` 参数设置一个全局 `asyncio.Semaphore`，**跨所有并行 LLM 阶段共享**（包括摘要、转换、优化的所有批次）。DeepSeek API 限制：

| 模型 | 并发上限 |
|------|---------|
| `deepseek-v4-pro` | 500 |
| `deepseek-v4-flash` | 2500 |

默认 20 极为保守。如果你的 API 等级允许更高，可上调至 50-100。

### 编剧风格指示 (`-s`)

`-s` 参数将一段自然语言注入到 **转换 (Conversion)** 和 **优化 (Optimization)** 两个阶段的 system prompt 中，以 `【编剧指示】` 块的形式出现。例如：

```bash
# 悬疑氛围
uv run python -m cli.pipeline novel/ -s "悬疑风格，注重环境氛围渲染，对白要简洁暗示性" -o out.yaml

# 黑暗改编
uv run python -m cli.pipeline novel/ -s "更加黑暗，加强角色内心冲突，削弱浪漫元素" -o out.yaml

# 喜剧化
uv run python -m cli.pipeline novel/ -s "喜剧风格，对话要幽默有趣，节奏明快" -o out.yaml
```

风格指示支持中英文。它**不会**被注入到摘要、RAG 或知识图谱构建阶段 — 仅影响剧本最终的文学表达形式。

## 环境变量

所有环境变量会由 `python-dotenv` 从 `backend/.env` 自动加载，然后可在运行时直接通过 `os.getenv()` 获取。完整的 `.env.example` 参考见 `backend/.env.example`。

### 必需

| 变量 | 说明 |
|------|------|
| `DEEPSEEK_API_KEY` | DeepSeek API Key（chat completions） |
| `OPENROUTER_API_KEY` | OpenRouter API Key（embeddings） |

### 可选 — LLM 调优

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `LLM_CONTEXT_WINDOW` | 模型自动检测 | 手动覆盖上下文窗口（tokens） |
| `LLM_MAX_OUTPUT_TOKENS` | 模型自动检测 | 手动覆盖最大输出 tokens |
| `LLM_MAX_CONCURRENCY` | 20 | 最大并发 LLM API 调用数 |
| `LLM_MAX_RETRIES` | 按阶段 1-3 | 全局覆盖重试次数 |

### 可选 — Embeddings / RAG

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | OpenRouter API base URL |
| `OPENROUTER_EMBEDDING_MODEL` | `nvidia/llama-nemotron-embed-vl-1b-v2:free` | Embedding 模型名称 |

## Pipeline 流程

每次运行经历 7 个 LLM 阶段 + 1 个导出阶段（共 8 步）：

```
源文本
  │
  ├─ 1. Chunking ────────────────────── 切分章节
  │    模型: Flash (LLM fallback 仅有)
  │    策略: 正则 → LLM fallback
  │    输入: 模式 — 目录输入跳过此阶段
  │
  ├─ 2. Summarization ──────────────── 章节摘要
  │    模型: Flash, 并行
  │    输出: 每章 100-200 字客观摘要
  │    用途: 作为转换阶段的"前情提要"注入
  │
  ├─ 3. RAG Index ──────────────────── 构建 FAISS 索引
  │    模型: text-embedding-3-small (OpenRouter)
  │    输出: 章级别文档向量
  │    用途: 跨章节上下文检索
  │
  ├─ 4. GraphRAG ───────────────────── 知识图谱提取
  │    模型: Pro
  │    输出: 实体节点 + 关系边
  │    策略: ≤5章 → 单次提取; >5章 → 逐章增量提取
  │    实体类型: character, location, item, event, organization
  │
  ├─ 5. Conversion ─────────────────── 章节 → 剧本场景
  │    模型: Flash, 并行
  │    输入: 段落组 + 前情摘要 + KG + RAG 上下文
  │    输出: 每章 N 个场景 (scene_id + heading + elements)
  │
  ├─ 6. Optimization ───────────────── 跨场景一致性检查
  │    模型: Pro, 批次并发
  │    检查: 人物弧光 / 地点连续性 / 时间线 / 对白风格
  │    容忍: 批次失败 → 保留原始场景, 不丢失
  │
  ├─ 7. Narrative Summary ──────────── 叙事梗概
  │    模型: Flash
  │    输入: 第 2 阶段生成的所有章节摘要
  │    输出: 一个段落的故事梗概
  │
  └─ 8. Export ──────────────────────── YAML / JSON
      输出: meta + characters + scenes + knowledge_graph
```

### 进度百分比

```
  0%  starting
  5%  chunking      (章节已拆分 → 直接跳到 5%)
 15%  summarizing   (摘要并行完成)
 25%  rag           (FAISS 索引构建完成)
 35%  graphrag      (KG 提取完成)
 35-75% converting  (每章转换完成一个 梯度上升)
 90%  optimizing    (优化完成)
100%  complete
```

### 输入模式

| 模式 | 触发条件 | 章节切分 | 说明 |
|------|---------|---------|------|
| **单文件** | `INPUT` 是一个 `.txt` 文件 | 正则 → LLM fallback | 适用于完整小说文本 |
| **目录** | `INPUT` 是一个目录 | 跳过 — 每文件一章 | 每个 `.txt`/`.md`/`.utf8` 文件为一个章节 |

## 输出格式

### YAML（默认）

```yaml
meta:
  source_file: 永恒至尊_剑游太虚
  source_chars: 11261
  chapter_count: 4
  scene_count: 19
  pipeline_version: 0.2.0
  chapter_summaries:
  - 李浮尘在练武场上被李云河三招击败...
  - 李浮尘在后山被一道金色流光击中眉心...

summary: 全文叙事梗概...

characters:
- id: n_01
  name: 李浮尘
  aliases:
  - 浮尘少爷
  properties:
    aliases: [...]
    traits: [骄傲, 坚毅, 悟性高]

scenes:
- scene_id: s_001
  heading: 外景 练武场 - 白天
  location: 练武场
  time_of_day: 白天
  characters_present:
  - n_01
  - n_02
  elements:
  - type: action
    content: 练武场上，李浮尘被李云河一掌击飞。
    source_ref:
      chapter_id: ch_00
      offset: [0, 22]
      confidence: estimated
  - type: dialogue
    content: '李云河: 李浮尘，再练十年你也不是我对手。'

knowledge_graph:
  nodes:
  - id: n_01
    name: 李浮尘
    node_type: character
    properties:
      aliases: [...]
      traits: [...]
  edges:
  - source_node_id: n_01
    target_node_id: n_02
    relation: enemy_of
    weight: 0.9
```

### JSON

解析上相同；使用 `script.model_dump_json(indent=2)` 序列化。

### 元素类型 (Fountain 兼容)

| `type` | 说明 | 示例 |
|--------|------|------|
| `action` | 动作/叙述 | `张三走进房间。` |
| `dialogue` | 对白（含说话者前缀） | `李云河: 你不够看。` |
| `heading` | Slug line / 场景标题 | `内景 大殿 - 日` |
| `transition` | 过渡（CUT TO, FADE IN 等） | `CUT TO:` |
| `parenthetical` | 表情/动作提示 | `(冷笑)` |
| `character` | 纯角色名 | `张三` |
| `note` | 编剧注释 | `此处导演待定` |

## 双向溯源

每个剧本元素都携带一个 `source_ref` 对象，建立从剧本片段到原文的**完全可审计的追溯链**：

```json
{
  "chapter_id": "ch_02",
  "offset": [1540, 1623],
  "confidence": "exact"
}
```

| 字段 | 说明 |
|------|------|
| `chapter_id` | 源章节标识符 |
| `offset` | 原文中的 `[start, end]` 字符偏移量 |
| `confidence` | `exact` — 精确字符串匹配; `estimated` — 启发式位置估算 |

### 溯源恢复策略（3 级回退）

LLM 往返会丢失 source_ref，因此转换和优化阶段通过以下恢复：

1. **精确匹配** — 元素内容作为子串在原文中出现
2. **前缀匹配** — 内容的前 10 个字符匹配
3. **位置估算** — 基于在总元素中的比例插值偏移

优化阶段额外应用按位置的回退（`optimized[i] ↔ original[i]`），并构建内容→ref 映射来恢复 LLM 可能在来回过程中轻微编辑的 source_ref。

## LLM 架构

### 模型路由

| 阶段 | 模型 | 温度 | JSON 模式 | 为何 |
|------|------|------|-----------|------|
| 章节切分 (fallback) | Flash | 0.1 | ✓ | 轻量结构任务 |
| 摘要 | Flash | 0.1 | ✗ | 自然语言输出 |
| 知识图谱 | Pro | 0.3 | ✓ | 需要深度理解关系 |
| 场景转换 | Flash | 0.5 | ✓ | 每章独立，Flash 足够 |
| 一致性检查 | Pro | 0.2 | ✓ | 跨场景推理需大模型 |
| 叙事梗概 | Flash | 0.3 | ✗ | 自然语言，轻度任务 |
| AI 对话 | Flash | 0.7 | ✗ | 创意对话 |

### 上下文预算

每个阶段使用边界感知的上下文预算：

```
安全输入字符数 = context_window × 0.6 (CJK 比率) × 0.6 (开销比率)
                = 1,000,000 × 0.6 × 0.6
                = 360,000 chars
```

- **段落切分器**：文本切分到段落边界（不是裸字符数切分）
- **短段落合并**：≤32 字符的段落与邻居合并
- 每个段落组永远在段落边界结束 — 绝不在句子中间

### 超时

所有 LLM 调用都配置 `httpx.Timeout(connect=10s, read=180s, write=10s, pool=5s)`。

## 错误处理与重试

### 重试策略

所有 LLM 调用都包裹了指数退避 + 抖动重试：

```
尝试 1 (t=0)        → 失败？
  等待 1-2s           ← 指数退避 + 随机抖动
尝试 2 (t≈1.5s)     → 失败？
  等待 2-4s
尝试 3 (t≈4.5s)     → 结果（放弃前最多等 30s）
```

### 重试次数（按阶段）

| 阶段 | 重试次数 | 理由 |
|------|---------|------|
| 切分 | 1 | 快速回退 |
| 摘要 | 1 | 可重新运行 |
| 知识图谱 | 2 | 中等成本 |
| 场景转换 | 2 | 中等成本 |
| 一致性检查 | 3 | 最高 — 跑这么久后丢失很糟 |
| AI 对话 | 1 | 实时交互 |

全局覆盖：设置 `LLM_MAX_RETRIES=5`。

### 可重试 vs 不可重试错误

**可重试**（暂时性）：
- `APIConnectionError` — 网络/SSL 失败
- `APITimeoutError` — 请求超时
- `RateLimitError` — 429 Too Many Requests
- `InternalServerError` — 5xx
- `httpx.ConnectError` / `httpx.ReadTimeout`

**不可重试**（立即抛出）：
- 400 / 401 / 403 / 404 — 客户端错误
- Pydantic 验证失败 — 格式漂移（平台错误，不是暂时性故障）

### 阶段失败容忍

| 阶段 | 失败行为 |
|------|---------|
| 摘要 | 返回空字符串 `""` |
| 知识图谱 | 返回空 `KnowledgeGraph()` |
| 场景转换 (单章) | 该章返回 `[]` — 不阻塞其他章 |
| 场景转换 (全部返回 `[]`) | 抛出 `RuntimeError` — 无可恢复 |
| 优化 (单批次) | 该批次保留原始场景 — 不阻塞其他批次 |

## 示例

### 基础用法

```bash
# 单个 .txt 文件
uv run python -m cli.pipeline novel.txt -o output.yaml

# 包含 .md 章节文件的目录
uv run python -m cli.pipeline chapters/ -o output.yaml

# 输出 JSON 到 stdout
uv run python -m cli.pipeline novel.txt --json

# 仅处理前 5 章（用于测试）
uv run python -m cli.pipeline novel.txt -n 5 -o preview.yaml
```

### 高级用法

```bash
# 全部参数：限制 + 并发 + 风格
uv run python -m cli.pipeline chapters/ \
  -n 10 \
  -c 50 \
  -s "电影感叙事，视觉化描写，对话简洁富有张力" \
  -o movie_style.yaml

# 高并发（信任 API 限制）
LLM_MAX_CONCURRENCY=100 uv run python -m cli.pipeline novel.txt -o output.yaml

# 调试模式（控制台日志）
uv run python -m cli.pipeline novel.txt --json 2>debug.log

# 管道处理
uv run python -m cli.pipeline novel.txt --json | python process.py
```

### Windows 注意事项

CLI 在启动时会自动将 stdout/stderr 重配置为 UTF-8 编码，以确保 CJK 字符能在 Windows 控制台正常输出。

## 模块索引

```
cli/
├── __init__.py              # 包标记
├── pipeline.py              # 主编排器 — run(), run_from_text(),
│                            #   run_from_chapters(), main() CLI
├── models.py                # Pydantic V2 数据模型 — Chapter, Scene,
│                            #   Element, Script, KnowledgeGraph 等
├── chunker.py               # 章节切分 — 正则 + LLM 回退
├── summarizer.py            # 章节摘要 — Flash, 100-200 字, 并行的
├── paragraph_splitter.py    # 段落切分 — 边界感知分组, ≤32 字符合并
├── rag_builder.py           # FAISS 索引 — OpenRouter embeddings,
│                            #   1536 维向量, build_index(), embed_texts()
├── graphrag_builder.py      # 知识图谱 — 单次 + 增量提取,
│                            #   5 种实体类型, 12 种关系类型
├── converter.py             # 场景转换 — 章节 → 剧本场景 (Flash)
├── optimizer.py             # 一致性检查 — 批次并发 (Pro)
├── exporter.py              # 序列化 — to_yaml(), to_json()
└── llm_router.py            # LLM 基础设施 — 模型路由, 上下文预算,
                             #   重试, 并发信号量, 超时
```

### 关键入口函数

| 函数 | 模块 | 说明 |
|------|------|------|
| `run(input_path, *, limit, style_direction)` | `pipeline.py` | CLI 顶层入口 — 分发到文件/目录路径 |
| `run_from_text(raw_text, *, limit, style_direction)` | `pipeline.py` | 从内存文本运行 pipeline |
| `run_from_chapters(chapters, *, faiss_index, kg, style_direction)` | `pipeline.py` | 从预构建章节运行 — API/缓存路径 |
| `split_chapters(text)` | `chunker.py` | 正则 → LLM 章节切分 |
| `summarize_chapter(chapter)` | `summarizer.py` | 单章摘要 |
| `build_index(chapters)` | `rag_builder.py` | 从头构建 FAISS |
| `extract_graph(chapters, faiss_index)` | `graphrag_builder.py` | 单次 KG 提取 |
| `extract_graph_incremental(chapters, faiss_index)` | `graphrag_builder.py` | 增量 KG 提取 |
| `convert_chapter(chapter, kg, rag_ctx, *, chapter_summary, style_direction)` | `converter.py` | 单章 → 场景 |
| `optimize(scenes, kg, style_direction)` | `optimizer.py` | 跨场景一致性 (async) |
| `to_yaml(script)` / `to_json(script)` | `exporter.py` | 序列化 |

### Programmatic API

除 CLI 外，pipeline 也可以作为库使用：

```python
import asyncio
from cli.pipeline import run, run_from_text, run_from_chapters
from cli.models import Chapter

# 从文件路径运行
script = asyncio.run(run("novel.txt", limit=5, style_direction="黑暗风格"))

# 从内存文本运行（带进度回调）
def on_progress(percent: int, stage: str):
    print(f"{percent}% — {stage}")

script = asyncio.run(run_from_text(
    novel_text,
    progress_callback=on_progress,
    source_name="my_novel",
    style_direction="喜剧风格",
))

# 从预构建章节运行（含 DB 缓存）
script = asyncio.run(run_from_chapters(
    chapters,
    progress_callback=on_progress,
    source_name="cached_run",
    faiss_index=cached_faiss,   # 跳过 stage 3
    kg=cached_kg,               # 跳过 stage 4
    style_direction="悬疑风格",
))

# 访问结果
print(script.summary)          # 叙事梗概
print(len(script.scenes))      # 场景数量
for scene in script.scenes:
    print(scene.heading)
    for elem in scene.elements:
        print(f"  [{elem.type}] {elem.content[:60]}...")
```
