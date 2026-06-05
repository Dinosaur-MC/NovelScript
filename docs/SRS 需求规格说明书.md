# NovelScript (析幕) 需求规格说明书

**项目名称**：NovelScript (析幕) – AI 驱动的长篇小说到结构化剧本转换系统
**版本**：v1.1
**日期**：2026-06-05
**作者**：Dinosaur_MC
**开发约束**：单人 72 小时，资金支持 ￥500~2000
**目标模型**：DeepSeek-v4-flash（轻量快速） / DeepSeek-v4-pro（高质量转换）

## 1. 引言

### 1.1 编写目的

本文档旨在完整定义 NovelScript 项目的功能需求、非功能需求、系统架构与接口规范，为 72 小时单人开发提供清晰的实施蓝图。目标读者为开发人员、评审专家及后续可能的维护者。

### 1.2 项目背景

大量小说作者希望将作品改编为影视或舞台剧本，但手工转换耗费大量时间，且需要同时精通文学叙事与剧本格式。现有工具多仅支持格式转换，缺乏对故事结构、角色关系、场景划分的深度理解。本项目利用大语言模型（LLM）自动完成从小说到 YAML 结构化剧本的转换，并提供原文追溯、知识图谱、在线预览等功能，大幅降低改编门槛。

### 1.3 适用范围

- 输入：3 章及以上中文/英文小说（支持粘贴、上传 .txt/.md、网页链接抓取）
- 输出：结构化剧本（YAML/JSON），兼容行业标准并附加增强字段
- 用户：网文作者、独立编剧、内容创作团队
- 平台：Web 应用，浏览器访问

### 1.4 术语与缩写

- **Scene（场景）**：剧本的基本叙事单元，通常对应一个连续时空内的情节段落。
- **Element（剧本元素）**：场景内部的原子单位，如对白（dialogue）、动作（action）、画面提示等。
- **source_ref**：自定义增强字段，指向小说原文的章节、段落编号，用于追溯和定位。
- **Knowledge Graph（知识图谱）**：以 JSON 图结构表示的角色、地点、事件及相互关系。

## 2. 总体描述

### 2.1 产品视角

NovelScript 是一个 Web 应用，用户通过浏览器访问，粘贴或上传小说文本后，系统自动分析并生成结构化剧本。前端提供原文阅读、剧本预览、知识图谱浏览的一体化界面，支持一键导出与原文跳转。

### 2.2 用户特征

- **小说作者**：具备文学素养，无技术背景，需要简单直观的操作流程。
- **编剧/策划**：熟悉影视剧本格式，关注场景划分、对白质量与角色一致性。
- **比赛评委**：注重技术难度、工程完整度、创新性与演示效果。

### 2.3 运行环境

- **前端**：现代浏览器（Chrome 90+, Firefox 88+, Edge 90+）
- **后端**：Linux 服务器，Python 3.10+，Docker 容器化部署
- **网络**：需要访问大模型 API（OpenAI 兼容接口），最低 1Mbps 带宽

### 2.4 设计与实现约束

- 单人开发，总时间 72 小时。
- 核心依赖外部 LLM 服务，必须处理 API 调用延迟、Token 限制与 JSON 格式不稳定性。
- 前端框架限定为 React + TypeScript，后端为 FastAPI。
- 剧本输出格式主选 YAML，辅选 JSON。
- 外部大模型调用成本需控制在预算内（￥500~2000），需合理分配 DeepSeek-v4-flash（日常对话、轻量抽取）与 DeepSeek-v4-pro（最终剧本转换、复杂推理）的使用比例。
- 所有用户生成内容（小说原文、转换结果、对话记录）必须持久化存储，支持历史回溯与状态恢复。

### 2.5 资金使用计划

- **模型 API 费用**（约 70%）：优先保证转换引擎的 Pro 模型调用，对话模块主要使用 Flash 模型。
- **云服务器**（约 20%）：轻量应用服务器，2C4G，按量或包月。
- **其他**（10%）：域名、存储备份、可能的第三方 TTS/图像 API 调用（若扩展）。

### 2.6 假设与依赖

- 用户上传的小说文本为纯文本或 Markdown 格式，且包含明确或可推断的章节分割。
- 小说样本的版权问题由用户自行负责。

## 3. 功能需求

### 3.1 小说输入模块

**3.1.1 文本粘贴与上传**

- 用户可在前端编辑器中直接粘贴小说文本（支持 Markdown 标题识别章节）。
- 提供文件上传按钮，支持 `.txt`、`.md` 格式，单文件大小不超过 5MB。

**3.1.2 链接抓取（可选，优先级 P1）**

- 输入公开小说网页 URL，后端抓取正文内容（仅提取 `<article>` 或特定 CSS 选择器内的文本）。
- 抓取失败时提示用户改用粘贴或上传。

**3.1.3 章节识别与手动调整**

- 后端自动按正则表达式（如“第[零一二三四五六七八九十百千0-9]+章”、“Chapter \d+”等）切分章节。
- 前端展示章节列表，允许用户合并、拆分或重新排序章节，调整结果反馈至后续处理。

### 3.2 LLM 预处理模块

**3.2.1 全文摘要生成**

- 调用 LLM 生成 100~200 字的故事梗概，用于后续场景一致性校验。
- 支持中文和英文输出（根据文本语言自动切换）。

**3.2.2 内容切分**

- 若用户未提供章节切分，LLM 根据语义自动将全文划分为逻辑章节（最多 10 章），每章提取标题。

**3.2.3 知识图谱构建**

- 从全文中提取：
    - 角色列表：姓名、别名、身份、性格简述
    - 地点列表：名称、描述
    - 角色间关系：关系类型（朋友、敌人、恋人等）、关系强度（强/弱）
- 输出为 JSON 图结构（nodes 和 edges），前端可渲染为力导向图。

### 3.3 剧本转换引擎

**3.3.1 场景切分与转换**

- 以章为单位，LLM 将叙事性文本转换为场景序列。
- 每个场景包含：
    - 场景标题（heading）：如“第1场 咖啡馆 白天”
    - 地点（location）
    - 时间（time_of_day：白天/夜晚/清晨等）
    - 出场角色（characters 列表）
    - 剧本元素序列（elements）：顺序排列的动作、对白、转场提示等。

**3.3.2 并发分块处理**

- 将各章并发发送给 LLM 进行转换，单章文本长度超过 8000 字时自动再分片。
- 使用异步任务队列，避免阻塞请求，前端显示实时处理进度。

**3.3.3 输出结构化与反序列化**

- LangChain 的 `JsonOutputParser` 将 LLM 返回的 JSON 反序列化为 Pydantic 场景模型。
- 校验失败时，自动重试或使用正则修复，最大重试次数 2。
- 所有场景按原文顺序合并，生成完整剧本数据结构。

**3.3.4 增强字段注入**

- 为每个 `element` 添加 `source_ref` 字段，指向原文出处（格式：`chapter:段落编号`）。
- 依据知识图谱，为 `character` 添加简要描述和关系链接。

### 3.4 输出与导出

**3.4.1 YAML/JSON 生成**

- 按定义的 Schema 序列化整个剧本为 YAML 文件（默认）及 JSON 文件。
- 在 YAML 头部的注释中写入元数据：转换时间、所用模型、小说源信息。

**3.4.2 前端下载与复制**

- 提供“下载 YAML”、“下载 JSON”、“一键复制到剪贴板”按钮。
- 下载文件命名格式：`novelscript_<小说标题>_<时间戳>.yaml`

### 3.5 剧本预览与交互

**3.5.1 分栏布局预览**

- 左侧：小说原文阅读器，支持滚动和高亮当前跳转段落。
- 中间：格式化剧本视图，类似剧本排版（角色：对白，动作斜体，场景标题加粗）。
- 右侧：知识图谱面板，展示角色关系图、地点列表。

**3.5.2 原文跳转定位**

- 点击剧本中的任意对白或动作，左侧原文自动滚动到对应段落并高亮。
- 通过 `source_ref` 的段落 ID 实现双向锚点跳转。

**3.5.3 角色/地点高亮**

- 在知识图谱中点击角色或地点，剧本内所有相关对白/动作高亮显示。

**3.5.4 简单播放演示（可选 P2）**

- 自动滚动剧本并高亮当前“播放”的元素，模拟场景流转。
- 播放速度可调（正常/快进）。

### 3.6 扩展功能（P2，时间充裕时实现）

- TTS 朗读：选中一句对白，调用浏览器内置语音合成或 ElevenLabs API 朗读。
- AI 场景图生成：为场景标题生成一张示意图片（调用 Stable Diffusion 或 DALL·E）。
- 多语言支持：小说语言自动检测，输出剧本语言可切换。

### 3.7 AI 辅助编辑与对话模块

**3.7.1 上下文感知对话**

- 用户可在右侧面板或弹窗中打开 AI 助手，基于当前完整转换上下文（包括原始小说、已生成的剧本、知识图谱）进行自然语言对话。
- 支持以下对话意图：
    - 询问某个场景的角色动机、情节合理性
    - 请求解释某段对白为什么这样改编
    - 建议修改某个场景的对白、动作或地点
    - 自动执行修改，如“把第3场的地点改成图书馆”
- 对话上下文自动注入当前关注的 Scene 信息与角色列表，确保 AI 回答紧扣内容。

**3.7.2 剧本实时修改应用**

- AI 提出的修改建议（如“将这场戏改成夜晚，并增加一句冲突对白”）可生成结构化补丁（diff）。
- 用户可一键“应用修改”，前端立即更新剧本 YAML/JSON 并同步预览视图。
- 修改历史记录在操作日志中，支持撤销（Undo）至上一状态（最多 5 步）。

**3.7.3 操作日志与版本控制**

- 每次手动编辑或 AI 修改均记录：时间、操作类型（AI建议应用 / 手动编辑）、变更字段、修改前后内容快照。
- 用户可查看所有历史操作，并回滚到任意历史版本。

**3.7.4 对话持久化**

- 所有对话记录关联至当前剧本任务，按时间戳存储，切换会话后依然可查看历史讨论。

## 4. 非功能需求

### 4.1 性能

- 3 章共约 2 万字的转换总时间 ≤ 90 秒（含 LLM 调用、并发处理、格式化）。
- 前端首次加载时间 ≤ 3 秒（gzip 压缩后资源 ≤ 2MB）。
- 支持 10 个并发用户而不显著增加单任务耗时（系统设计为每用户独立任务队列）。

### 4.2 可用性

- 界面简洁，核心操作不超过 3 步：输入 → 点击转换 → 浏览/导出。
- 提供友好的错误提示，如“文本过短，请至少输入 3 章内容”、“API 暂时不可用，请稍后重试”。
- 转换过程中显示步骤进度条（预处理 → 正在构建第 X/总章数 章）。

### 4.3 可靠性

- LLM 输出的 JSON 解析失败时，自动请求 LLM 修正，最多 2 次重试，仍失败则返回部分结果并警告用户。
- 对于不支持的格式或异常输入，系统不会崩溃，而是返回规范化错误信息。

### 4.4 安全性

- API 密钥仅存于后端环境变量，不暴露给前端。
- 对用户上传的文本内容不做永久存储，处理完成后 1 小时自动从服务器删除。
- 前端使用 DOMPurify 消毒渲染内容，防止 XSS。

### 4.5 可维护性

- 后端使用 FastAPI 自动生成交互式 API 文档（/docs）。
- 核心 Prompt 以独立文件或配置项管理，方便调优。
- Docker Compose 一键部署，依赖明确。
- 采用 MySQL 关系数据库作为任务元数据与对话记录的存储。

### 4.6 可扩展性

- Schema 设计预留扩展字段（`meta`），方便日后兼容更多剧本标准。
- 知识图谱可替换为图数据库存储。
- 转换引擎支持插件式新增其他输出格式（如 Fountain、Final Draft XML）。

### 4.7 数据持久性

- 用户提交的小说、生成的剧本、对话记录在服务器上至少永久保留 3 部，用户可手动删除。
- 任务结果支持通过分享链接临时访问（可选 P2）。

## 5. 系统架构

### 5.1 总体架构图

```text
[浏览器: React SPA]
      |
      | HTTP/REST
      v
[Nginx 反向代理]
      |
      v
[FastAPI 应用服务器]
      ├─ /api/novel/upload          (接收文本)
      ├─ /api/novel/preprocess      (触发预处理)
      ├─ /api/novel/convert         (开始转换)
      ├─ /api/novel/status/{id}     (任务状态)
      └─ /api/novel/result/{id}     (获取结果)
      |
      ├─ LLM Service (OpenAI API)
      └─ 数据库 (MySQL、FAISS)
```

### 5.2 前端架构

- 框架：React 18 + TypeScript
- UI 库：Ant Design 5
- 状态管理：React Context + useReducer
- 文本编辑器：TipTap（支持 Markdown）
- 图表：vis.js 或 D3 用于知识图谱
- 构建工具：Vite

### 5.3 后端架构

- Web 框架：FastAPI
- 异步任务：asyncio + asyncio.gather（轻量并发）
- 数据处理：Pydantic v2、PyYAML、LangChain
- LLM 集成：openai Python 包（兼容 DeepSeek 等）
- 部署：Docker + Nginx + BaoTa
- `editor_service`：处理对话请求，管理上下文注入，生成修改建议与结构化补丁。
- `storage_layer`：基于 SQLite 的任务存储、对话记录、操作日志表。
- 模型路由：根据功能复杂度自动选择 flash 或 pro 模型（转换使用 pro，对话使用 flash，预处理两者按需）。

### 5.4 数据流

1. 用户提交文本 → 后端生成任务 ID，存储原文至临时文件。
2. 调用预处理 API → LLM 输出摘要、角色、章节切分 → 缓存为 JSON。
3. 用户确认章节分割后调用转换 API → 后端分割章节并发调用 LLM → 各场景 JSON 合并。
4. Pydantic 校验并注入 source_ref → 生成 YAML/JSON → 存入任务结果。
5. 前端轮询状态 → 获取结果 → 渲染剧本视图和知识图谱。
6. 用户在预览界面打开 AI 对话 → 前端发送当前 scene_id 与用户消息 → 后端构造包含原文、剧本片段、知识图谱的 Prompt → 调用 flash 模型生成回复与可选补丁。
7. 前端展示回复，用户请求应用补丁 → 后端校验补丁有效性 → 更新剧本 JSON → 返回新 YAML 并记录操作日志。

## 6. 数据设计

### 6.1 核心数据结构（YAML Schema）

详见附件《NovelScript YAML Schema 设计文档》草案，此处简述顶层结构：

```yaml
script:
  meta:
    title: "小说标题"
    author: "原作者"
    converted_by: "NovelScript v1.0"
    model: "deepseek-v3"
    timestamp: "2026-06-05T12:00:00Z"
  summary: "故事摘要..."
  characters:  # 去重角色列表
    - name: "艾伦"
      description: "年轻程序员"
  scenes:
    - scene_id: 1
      heading: "第1场 咖啡馆 白天"
      location: "纽约 中央咖啡馆"
      time_of_day: "白天"
      characters_present: ["艾伦"]
      elements:
        - type: "action"
          content: "艾伦推开玻璃门，风铃响起。"
          source_ref: "ch2.para5"
        - type: "dialogue"
          speaker: "艾伦"
          line: "一杯美式，谢谢。"
          source_ref: "ch2.para6"
        ...
  knowledge_graph:
    nodes: ...
    edges: ...
```

设计原则：以场景（Scene）为顶层叙事单位，内部元素顺序严格保持叙事流；每个元素携带原文锚点；角色关系图与场景解耦，便于独立展示。

### 6.2 任务状态模型（Pydantic）

```python
class TaskStatus(str, Enum):
    PENDING = "pending"
    PREPROCESSING = "preprocessing"
    CONVERTING = "converting"
    COMPLETED = "completed"
    FAILED = "failed"

class Task(BaseModel):
    id: str
    status: TaskStatus
    progress: int = 0        # 0-100
    summary: str | None = None
    characters: list[dict] | None = None
    result_yaml: str | None = None
    result_json: dict | None = None
    error_message: str | None = None
```

### 6.3 持久化存储结构（MySQL）

**选型说明**：采用 MySQL 8.0，利用其事务支持、行级锁与良好的并发读性，保障多用户同时转换与编辑时数据一致。部署时将 MySQL 作为独立容器，通过 Docker Compose 与 FastAPI 后端协作。

**建表语句概要**：

```sql
-- 用户任务主表
CREATE TABLE tasks (
    id VARCHAR(36) PRIMARY KEY COMMENT 'UUID',
    source_text LONGTEXT NOT NULL COMMENT '原始小说全文',
    status ENUM('pending','preprocessing','converting','completed','failed') NOT NULL DEFAULT 'pending',
    summary TEXT COMMENT '预处理摘要',
    characters_json JSON COMMENT '角色列表',
    knowledge_graph_json JSON COMMENT '知识图谱',
    script_yaml LONGTEXT COMMENT '最终剧本YAML',
    script_json JSON COMMENT '最终剧本JSON',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_status (status),
    INDEX idx_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 章节表（可选，便于独立引用）
CREATE TABLE chapters (
    id INT AUTO_INCREMENT PRIMARY KEY,
    task_id VARCHAR(36) NOT NULL,
    chapter_index INT NOT NULL COMMENT '章节序号',
    title VARCHAR(255),
    content LONGTEXT NOT NULL,
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
    INDEX idx_task_chapter (task_id, chapter_index)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 操作日志表（支持撤销）
CREATE TABLE operations (
    id INT AUTO_INCREMENT PRIMARY KEY,
    task_id VARCHAR(36) NOT NULL,
    timestamp DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    type ENUM('manual_edit','ai_patch','rollback') NOT NULL,
    target VARCHAR(255) COMMENT '修改目标，如scenes[0].elements[1].line',
    diff_json JSON COMMENT '变更补丁',
    previous_json JSON COMMENT '修改前片段快照',
    applied TINYINT(1) NOT NULL DEFAULT 1 COMMENT '是否已应用',
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
    INDEX idx_task_ops (task_id, timestamp)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- AI 对话记录表
CREATE TABLE dialogues (
    id INT AUTO_INCREMENT PRIMARY KEY,
    task_id VARCHAR(36) NOT NULL,
    role ENUM('user','assistant') NOT NULL,
    content TEXT NOT NULL,
    patch_json JSON COMMENT '若消息包含补丁则记录',
    timestamp DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
    INDEX idx_task_dialog (task_id, timestamp)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

**关键设计点**：

- 使用 **JSON 字段** 存储非结构化元数据，避免频繁 ALTER TABLE，且便于直接用 MySQL 的 JSON 函数查询补丁内容或角色关系。
- 外键级联删除，保证数据一致性，清理任务时自动移除关联章节、日志与对话。
- `operations.previous_json` 保存修改前片段，支持可靠的撤销链（前端可限制最多回滚 5 步，后端保留完整历史）。
- 生产环境建议为 `tasks.script_yaml` 等大字段开启压缩或使用外部对象存储，但 72 小时项目直接存库即可。

## 7. 接口需求

### 7.1 RESTful API

**7.1.1 上传小说**

- `POST /api/novel/upload`
- Body: `{ "content": "文本内容..." }` 或 Form-Data `file`
- Response: `{ "task_id": "uuid", "chapters": ["第1章 开始", ...] }`

**7.1.2 启动预处理**

- `POST /api/novel/preprocess`
- Body: `{ "task_id": "uuid", "chapter_boundaries": [...] }`（可选，用于自定义切分）
- Response: `{ "task_id": "uuid", "status": "preprocessing" }`

**7.1.3 查询任务状态**

- `GET /api/novel/status/{task_id}`
- Response: `Task` 模型

**7.1.4 获取转换结果**

- `GET /api/novel/result/{task_id}`
- Response: 完整的 script JSON 结构

**7.1.5 抓取网页（可选）**

- `POST /api/novel/fetch`
- Body: `{ "url": "https://..." }`
- Response: `{ "content": "抓取到的文本..." }`

### 7.2 外部接口

- Deepseek API：`https://api.deepseek.com` 或 OpenAI 兼容接口，使用 `deepseek-v4-flash` 和 `deepseek-v4-pro` 模型。

### 7.3 AI 编辑对话接口

**7.3.1 发送对话消息**

- `POST /api/editor/chat/{task_id}`
- Body: `{ "message": "把第2场的地点改为图书馆", "context": { "scene_id": 2 } }`
- Response (SSE 或一次性):
    ```json
    {
        "reply": "好的，我已将第2场地点改为图书馆...",
        "patch": {
            "target": "scenes[1].location",
            "old_value": "咖啡馆",
            "new_value": "图书馆"
        }
    }
    ```

**7.3.2 应用补丁**

- `POST /api/editor/apply_patch/{task_id}`
- Body: `{ "patch": { ... } }`
- Response: `{ "success": true, "updated_script": { ... } }`

**7.3.3 撤销操作**

- `POST /api/editor/undo/{task_id}`
- Response: 回滚后的完整剧本

**7.3.4 获取操作历史**

- `GET /api/editor/history/{task_id}`
- Response: `{ "operations": [...] }`

## 8. 项目计划（72 小时）

| 时间段        | 任务                                                                                              | 产出                            |
| ------------- | ------------------------------------------------------------------------------------------------- | ------------------------------- |
| **D0（8h）**  | 项目初始化，前后端骨架，小说上传/章节切分，预处理 API 调通                                        | 能粘贴文本并返回摘要和角色列表  |
| **D1（12h）** | 知识图谱构建，场景切分与转换引擎 Prompt 调试，并发调用，YAML 生成                                 | 端到端生成 3 章样本的 YAML 剧本 |
| **D2（12h）** | 前端剧本预览组件，原文跳转，知识图谱面板，导出功能，AI 对话面板 UI，对接聊天接口，UI 打磨         | 完整可交互的 Web 应用原型       |
| **D3（8h）**  | 编写 Schema 设计文档，Docker 部署，异常处理，录制演示视频，调试对话上下文注入准确性，编写测试用例 | 上线演示、提交材料              |

风险缓释：D0 晚若预处理失败，回退为简单章节正则切分；D1 若 JSON 解析不稳定，增加正则兜底；D2 可用简化版布局确保可演示。

## 9. 测试方案

### 9.1 测试目标

验证小说→剧本转换的正确性、AI 编辑功能的可用性、数据持久化完整性。

### 9.2 功能测试用例

| 编号  | 场景          | 操作                                                             | 预期结果                                                  |
| ----- | ------------- | ---------------------------------------------------------------- | --------------------------------------------------------- |
| TC-01 | 标准小说输入  | 粘贴包含3章的中文小说，点击转换                                  | 返回合理 YAML，场景数≥1，角色提取正确，包含 source_ref    |
| TC-02 | 章节自动识别  | 输入以“第X章”分割的文本                                          | 前端展示正确的章节列表，可手动调整                        |
| TC-03 | 英文小说处理  | 输入英文小说                                                     | 同样输出结构化剧本，语言为英文                            |
| TC-04 | 超长文本分片  | 提交单章 12000 字                                                | 系统自动分片处理，无报错，场景连贯                        |
| TC-05 | 知识图谱构建  | 预处理完成                                                       | 返回角色节点与关系边，前端可渲染                          |
| TC-06 | 原文跳转      | 点击某句对白的 source_ref                                        | 左侧原文滚动到对应段落并高亮                              |
| TC-07 | AI 对话与补丁 | 在剧本界面询问“为什么这里冲突这么弱”，然后请求“增加一句冲突对白” | AI 给出合理解释，并生成修改补丁，应用后剧本更新、预览刷新 |
| TC-08 | 撤销修改      | 应用补丁后点击撤销                                               | 剧本回退至上个状态，操作历史正确记录                      |
| TC-09 | 异常输入      | 粘贴无章节散文、空文本、纯数字                                   | 系统提示“请提供有效小说文本”，不崩溃                      |
| TC-10 | JSON 格式修复 | 模拟 LLM 返回缺少括号的 JSON                                     | 系统自动重试或正则修复，仍失败则返回部分结果并提示        |

### 9.3 测试环境与方法

- 使用固定的样本小说作为测试输入（中/英文各一篇），保证可重复。
- 自动化测试脚本（pytest）覆盖 API 输入输出校验，前端 E2E 测试可使用简版手动执行。
- 在提交前必须通过所有核心用例（TC-01~08）。

## 10. 附录

### 10.1 模型使用策略

- **DeepSeek-v4-pro**：用于剧本转换（高难度生成，需强一致性），预处理中的角色关系抽取。
- **DeepSeek-v4-flash**：用于对话交流、轻量内容摘要、章节切分、简单补丁生成。
- 成本控制：单次转换按 2 万字估算，pro 模型输入约 15K tokens，输出约 5K tokens，成本约 ￥0.05/次；flash 成本极低。预算可支持数千次完整转换与大量对话，足够比赛演示与测试。

### 10.2 用户界面原型（文字描述）

- 三栏布局：左-小说原文（可编辑），中-剧本预览（带高亮与操作按钮），右-知识图谱 + AI 对话切换面板。
- 底部浮动按钮：转换进度条、导出菜单。

### 10.3 参考标准

- **Final Draft**：行业剧本写作软件，格式为 .fdx（XML）。
- **Fountain**：纯文本剧本标记语言，简单易读。
- 本项目 YAML Schema 综合考虑了以上标准的字段映射与可读性。
