# NovelScript YAML Schema 设计说明

- **版本**: 2.0.0
- **状态**: 评审验收阶段
- **核心基准**: Fountain 1.1 Specification, 影视工业剧本规范
- **关联文档**: [SRS 需求规格说明书](./SRS%20需求规格说明书.md) §6.1–§6.4

---

## 1. 设计愿景与核心原则

本设计方案将 YAML Schema 定位为 **"具备零信息丢失往返能力 (Round-trip Fidelity) 的最终交付产物"**，而不仅是中间表示层（IR）。这意味着任意合法的 Fountain 1.1 剧本均可无损转换为 YAML，反之亦然。

| 核心原则                   | 详细说明                                                                                                                                                                                                                                |
| :------------------------- | :-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Fountain 1.1 100% 同构** | 完整支持 Fountain 1.1 的"显式强制 (Use The Force)"语法 (`@`, `!`, `~`, `>`)、Boneyard 批注、Section/Synopsis 结构及 Title Page 规范。                                                                                                   |
| **作者意图绝对保真**       | 严格遵循业界"作者优先"原则。例如 `(CONT'D)` 视为作者输入的文本片段予以精确保留，拒绝系统自作主张的"智能插入"。                                                                                                                          |
| **原子级双向溯源**         | `source_ref` 机制下沉至 Scene 与每一个 Element，支持基于字符偏移量 (Offset) 的毫秒级双向高亮联动。                                                                                                                                      |
| **逻辑块与物理行解耦**     | YAML 采用"逻辑块 (Logical Block)"聚合（如将角色、括号提示、对白聚合为一个 `dialogue_block`），导出引擎负责拆解为 Fountain 的"物理行"。                                                                                                  |
| **结构化兜底**             | 每个结构化字段（如 `heading`）同时保留原始文本 (`text`) 与拆解后的结构化子字段，确保在解析失败时仍具备降级回退能力。                                                                                                                    |
| **强校验**                 | 对应 Pydantic V2 严格模型，非法输出触发应用层重试（指数退避，每阶段 1-3 次可配），连接/超时/限流自动恢复。降级返回已解析部分，管道绝不崩溃。                                                                                                                                                        |
| **版本控制原生支持**       | YAML 文本格式天然适配 Git diff/merge，支持原作者、编剧、制片人异步协作与全历史溯源——这是 NovelScript 在 AI 辅助创作之外的第二核心竞争力。                                                                                               |
| **Fountain 互补定位**      | Fountain 1.1 是"导出友好的中间层"，并非行业交付终点。YAML Schema 在 100% 兼容 Fountain 往返的基础上，通过 `metadata` 扩展字段承载小说改编所需的高维叙事信息（闪回、多时间线、内心独白等），弥补 Fountain 在处理复杂叙事方面的语法空白。 |

## 2. Fountain 1.1 的市场局限与 Schema 扩展策略

Fountain 1.1 在全球剧本行业中的实际地位，决定了 NovelScript YAML Schema 不能仅仅是一个 "Fountain 的 YAML 映射层"——它必须在 Fountain 之上补位小说改编场景所必需的叙事维度。

> [!NOTE]
> 本节数据来源于 [Fountain 1.1 在全球小说改编剧本行业的地位与价值评估报告](../reports/边缘化的选择：Fountain%201.1%20在全球小说改编剧本行业的地位与价值评估.pdf)。

### 2.1 Fountain 的市场现实

| 维度             | 现状                                                                                                                                  |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| **市场渗透率**   | 全球剧本写作软件市场中，Fountain 生态（Highland + Slugline 等）合计占有率**不足 10%**。                                               |
| **行业主流**     | 北美市场被 Final Draft（~54% 从业者占有率）、Fade In 等商业软件主导，《Three Page Challenge》调查中无一参赛者使用 Fountain 原生工具。 |
| **权威平台认可** | The Black List（连接编剧与电影公司的关键平台）未提供 Fountain 的官方支持或格式指南。                                                  |
| **核心用户群**   | 技术背景深厚的独立创作者、程序员型编剧、小型协作团队——"忠实但边缘"的利基群体。                                                        |

### 2.2 Fountain 在小说改编场景中的已知短板

小说改编剧本的工作流具有**周期长、修改频繁、叙事结构复杂、涉及多方（原作者、编剧、制片人）协作**的特点。Fountain 1.1 的极简语法在这些场景中暴露出一系列结构性空白：

| 叙事手法              | Fountain 1.1 的支持程度                               | 小说改编中的实际需求                                             |
| --------------------- | ----------------------------------------------------- | ---------------------------------------------------------------- |
| **闪回 / 闪前**       | 无内置专用语法，需依赖 `boneyard` 注释或缩进示意      | 长篇小说常见非线性叙事，需精确标记时间锚点与回溯区间             |
| **画外音 (V.O.)**     | 仅通过 `(V.O.)` 字符扩展标记，无结构化的声源/层级区分 | 改编中常见：客观旁白、角色内心独白（内省）、信件朗读等多种子类型 |
| **内心独白 / 意识流** | 无专用语法；可能用斜体或 `boneyard` 绕过              | 小说文本的核心特征，需在剧本中明确区分"外部对白"与"内部意识"     |
| **多时间线并行**      | 无内置机制，完全依赖场标自由文本推断                  | 改编中常见的平行叙事、交叉剪辑结构，需时间线级别标识             |
| **蒙太奇 / 快切**     | 无专用语法，仅能用连续短 Action 行模拟                | 电影化改编的重要技法，需语义标记和节奏控制                       |
| **信函 / 文档朗读**   | 无内置区分机制                                        | 小说中常见的文本嵌入形式，剧本中需明确标注来源和朗读模式         |

### 2.3 YAML Schema 的补位策略

基于上述分析，NovelScript YAML Schema 采用**分层扩展**策略：

```
┌──────────────────────────────────────────────┐
│  Layer 0: Fountain 1.1 100% 同构层           │
│  ├─ 8 种元素类型 (§5.6)                       │
│  ├─ Round-trip Fidelity (YAML ↔ Fountain)    │
│  └─ Fountain 导出 → Highland/Slugline → PDF   │
├──────────────────────────────────────────────┤
│  Layer 1: 结构化增强层                        │
│  ├─ heading 拆解 (int_ext, location, time)    │
│  ├─ dialogue_block 逻辑聚合                   │
│  ├─ source_ref 三维溯源                       │
│  └─ character_extension 显式化                │
├──────────────────────────────────────────────┤
│  Layer 2: 叙事扩展层 (metadata)               │
│  ├─ narrative_type (闪回/旁白/内心独白/...)    │
│  ├─ timeline_id (多时间线标记)                 │
│  ├─ vo_source (画外音来源区分)                 │
│  └─ 其他小说改编专用标记 (§12)                 │
├──────────────────────────────────────────────┤
│  Layer 3: 渲染与交付层                        │
│  ├─ Fountain 导出 (中间格式, 兼容现有工具链)   │
│  └─ 直接 PDF 渲染 (跳过 Fountain, 行业合规)    │
└──────────────────────────────────────────────┘
```

**核心设计原则**：

1. **Fountain 是中间层，不是终点**：Fountain 导出用于兼容 Highland/Slugline 等现有工具链；平台同时内置直接 PDF 渲染引擎，生成符合行业格式的交付物。

2. **`metadata` 字段即补位入口**：所有 Fountain 原生不支持、但小说改编必需的叙事信息，均通过各层级的 `metadata` 字段承载，**绝不污染** Fountain 兼容层——确保 YAML → Fountain → YAML 往返不受影响。

3. **叙事元数据下沉至元素级**：`narrative_type`、`timeline_id` 等标记可作用于单个 Element（如一句内心独白对白），而非粗粒度的 Scene 级别，实现精细的叙事结构建模。

4. **双重导出路径**：
    - **路径 A**: `YAML → Fountain 1.1 → Highland/Slugline → PDF`（利用现有工具链）
    - **路径 B**: `YAML → NovelScript Renderer → PDF`（跳过 Fountain，原生渲染，支持叙事元数据驱动的智能排版）

## 3. Fountain 1.1 语法映射全景图

以下矩阵是转换引擎正确性的**黄金验收标准**。

| Fountain 1.1 元素  | 语法特征 / 强制语法         | YAML Schema 映射策略                                                   |
| :----------------- | :-------------------------- | :--------------------------------------------------------------------- |
| **Title Page**     | `Key: Value` 键值对         | 独立 `title_page` 字典，支持多行值。系统元数据剥离至 `system_meta`。   |
| **Scene Heading**  | `INT. / EXT.` 或 `.` 强制   | `heading` 对象，含 `is_forced` (对应 `.`) 与结构化拆解字段。           |
| **Action**         | 纯文本 或 `!` 强制          | `type: "action"`，含 `is_forced` 布尔值。                              |
| **Character**      | 全大写 或 `@` 强制          | `dialogue_block.character_name`，含 `is_character_forced` (对应 `@`)。 |
| **Parenthetical**  | `(text)`                    | `dialogue_block.parenthetical`，保留原始大小写。                       |
| **Dialogue**       | 纯文本                      | `dialogue_block.dialogue`。                                            |
| **Dual Dialogue**  | 右侧对话 `^`                | `dialogue_block.is_dual` 布尔值。                                      |
| **Lyrics**         | `~` 前缀                    | `type: "lyric"` 独立元素。                                             |
| **Transition**     | 全大写 `:` 结尾 或 `>` 强制 | `type: "transition"`，含 `is_forced` (对应 `>`)。                      |
| **Boneyard**       | `/* comment */`             | `type: "boneyard"` (替代非标准 `note`)，支持多行。                     |
| **Page Break**     | `===`                       | `type: "page_break"` 独立元素。                                        |
| **Section**        | `#`, `##`, `###`, `####`    | `type: "section"`，含 `level` (1-4)。                                  |
| **Synopsis**       | `=` 前缀                    | `type: "synopsis"`。                                                   |
| **(CONT'D) / EXT** | 角色名后括号内容            | 作为 `character_extension` 文本存储，**禁止系统自动生成**。            |
| **Centered Text**  | `> text <`                  | `type: "action"` + `is_centered: true`。                               |

## 4. 层级总览

```
Script (剧本)
├── title_page              → Fountain 标准标题页 (Title, Author, Draft date, Contact...)
├── system_meta             → 系统级元数据 (model, timestamp, schema_version, document_id)
├── summary                 → 全局梗概 (纯文本)
├── characters[]            → 角色词典
│   ├── id                  → 全局唯一 ID (char_01, char_02, ...)
│   ├── name                → 角色名
│   ├── aliases[]           → 别名/绰号 (可选)
│   ├── description         → 性格/外貌/身份简述
│   └── metadata            → 扩展字段
├── scenes[]                → 场景序列 (保持叙事顺序)
│   ├── scene_id            → 唯一场景 ID (S001, S002, ...)
│   ├── heading             → 结构化场标对象
│   │   ├── text            → 原始完整文本 (兜底用)
│   │   ├── int_ext         → INT | EXT | INT/EXT | EST | null
│   │   ├── location        → 地点名称
│   │   ├── time_of_day     → 标准枚举: DAY | NIGHT | DAWN | DUSK | LATER | CONTINUOUS
│   │   └── is_forced       → 是否以 `.` 强制 (Fountain 1.1)
│   ├── source_ref          → 场景级溯源锚点
│   ├── elements[]          → 剧本元素序列 (按时间顺序)
│   │   ├── type            → action | dialogue_block | transition | lyric | boneyard | section | synopsis | page_break
│   │   ├── ...             → 各类型专有字段 (详见 §5)
│   │   └── source_ref      → 元素级溯源锚点
│   └── metadata            → 场景级扩展字段
└── knowledge_graph         → 全局知识图谱
    ├── nodes[]             → 实体节点
    └── edges[]             → 关系边
```

## 5. 字段详细规格

### 5.1 `title_page` — Fountain 标准标题页

与系统元数据**物理隔离**，确保导出的 `.fountain` 文件头部纯净、合规。

```yaml
title_page:
    Title: "星辰低语"
    Credit: "改编"
    Author: "NovelScript AI"
    Source: "原著: 刘慈欣"
    Draft date: "2026-06-05"
    Contact: |
        NovelScript Studio
        contact@novelscript.ai
```

| 字段         | 类型  | 必填 | 说明                                |
| ------------ | ----- | ---- | ----------------------------------- |
| `Title`      | `str` | 是   | 剧本标题。                          |
| `Credit`     | `str` | 否   | 署名类型 (如 "改编"、"原创")。      |
| `Author`     | `str` | 是   | 作者 / 改编者声明。                 |
| `Source`     | `str` | 否   | 原著来源。                          |
| `Draft date` | `str` | 否   | 草稿日期，格式灵活。                |
| `Contact`    | `str` | 否   | 联系信息，支持多行（缩进 4 空格）。 |
| `Notes`      | `str` | 否   | 备注。                              |

**Fountain 导出规则**: 逐行输出 `Key: Value`，多行值缩进 4 空格，键值块以空行结束。

### 5.2 `system_meta` — 系统内部元数据

```yaml
system_meta:
    document_id: "doc_8f3a" # 全局溯源根 ID
    model: "deepseek-v4-pro" # 生成所用的 LLM 模型
    timestamp: "2026-06-05T12:00:00Z" # ISO 8601 UTC
    schema_version: "2.0.0" # Schema SemVer
    language: "zh-CN" # IETF BCP 47
    source_word_count: 15234 # 可选: 原文字数
    warnings: [] # 可选: 运行时警告列表 (如偏移漂移)
```

| 字段                | 类型        | 必填 | 说明                                      |
| ------------------- | ----------- | ---- | ----------------------------------------- |
| `document_id`       | `str`       | 是   | 全局溯源根 ID，对应 tasks 表或原文 Hash。 |
| `model`             | `str`       | 是   | LLM 模型标识。                            |
| `timestamp`         | `datetime`  | 是   | 生成时间，ISO 8601 UTC。                  |
| `schema_version`    | `str`       | 是   | Schema 版本号，SemVer 格式。              |
| `language`          | `str`       | 否   | 原文语言，IETF BCP 47，默认 `"zh-CN"`。   |
| `source_word_count` | `int`       | 否   | 原著字数统计。                            |
| `warnings`          | `list[str]` | 否   | 运行时警告（偏移漂移、格式降级等）。      |

**校验规则**:

- `model` 必须为已注册枚举值 (`deepseek-v4-pro` | `deepseek-v4-flash`)。
- `schema_version` 必须符合 SemVer 格式。
- `timestamp` 必须符合 ISO 8601 格式。
- `document_id` 全局唯一，不可为空。

### 5.3 `summary` — 全局梗概

```yaml
summary: "在废弃的星际飞船上，颓废的领航员林明与冷酷的仿生人艾娃展开了一场关于宇宙边缘与人类情感的对话。"
```

- **类型**: `str`
- **约束**: 不超过 500 字符，推荐 80–200 字。
- **用途**: 前端概览卡片 + LLM 对话全局上下文注入。

### 5.4 `characters` — 角色词典

```yaml
characters:
    - id: "char_01"
      name: "林明"
      aliases: ["老林", "领航员"]
      description: "30岁，颓废的星际领航员，右眼有机械义眼。"
      metadata: {}
    - id: "char_02"
      name: "艾娃"
      aliases: []
      description: "AI 仿生人，冷静的外表下隐藏着对人类情感的好奇。"
      metadata: {}
```

| 字段          | 类型        | 必填           | 说明                               |
| ------------- | ----------- | -------------- | ---------------------------------- |
| `id`          | `str`       | 是             | 全局唯一，推荐 `char_NN` 格式。    |
| `name`        | `str`       | 是             | 角色名，不可为空。                 |
| `aliases`     | `list[str]` | 否 (默认 `[]`) | 别名列表，过滤空字符串。           |
| `description` | `str`       | 是             | 1–3 句角色描述，用于 Prompt 注入。 |
| `metadata`    | `dict`      | 否 (默认 `{}`) | 扩展字段 (如 `age`, `gender`)。    |

### 5.5 `scenes` — 场景序列

#### 5.5.1 Scene 顶层字段

```yaml
scenes:
    - scene_id: "S001"
      heading: # 结构化场标 (见 §5.5.2)
          text: "内景. 废弃飞船驾驶舱 - 夜晚"
          int_ext: "INT"
          location: "废弃飞船驾驶舱"
          time_of_day: "NIGHT"
          is_forced: false
      source_ref: # 场景级溯源 (覆盖整个场景)
          document_id: "doc_8f3a"
          chapter_id: "ch_02"
          offset: [1400, 1850]
      elements: [...] # 剧本元素序列 (见 §5.6)
      metadata:
          estimated_duration_sec: 120
          tone: "压抑、忧伤"
```

| 字段                 | 类型            | 必填 | 说明                                           |
| -------------------- | --------------- | ---- | ---------------------------------------------- |
| `scene_id`           | `str`           | 是   | 全局唯一，推荐 `Snnn` 格式。                   |
| `heading`            | `Heading`       | 是   | 结构化场标对象，详见 §5.5.2。                  |
| `source_ref`         | `SourceRef`     | 否   | 场景级溯源锚点，覆盖整个场景的原文区间。       |
| `characters_present` | `list[str]`     | 否   | 出场角色 ID 列表，必须引用 `characters[].id`。 |
| `elements`           | `list[Element]` | 是   | 场景内按时间顺序排列的元素序列，不可为空。     |
| `metadata`           | `dict`          | 否   | 场景级扩展数据。                               |

#### 5.5.2 `heading` — 结构化场标

```yaml
heading:
    text: "内景. 废弃飞船驾驶舱 - 夜晚" # 原始完整文本 — 兜底字段
    int_ext: "INT" # 枚举, 可为 null
    location: "废弃飞船驾驶舱" # 地点名称
    time_of_day: "NIGHT" # 标准枚举
    is_forced: false # 若为 true, 导出时前缀加 `.`
```

| 字段          | 类型   | 必填 | 说明                                                                |
| ------------- | ------ | ---- | ------------------------------------------------------------------- |
| `text`        | `str`  | 是   | 原始场标文本，当结构化解析失败时作为兜底导出。                      |
| `int_ext`     | `str`  | 否   | 枚举: `"INT"`, `"EXT"`, `"INT/EXT"`, `"EST"`, `null` (未知)。       |
| `location`    | `str`  | 是   | 地点名称。                                                          |
| `time_of_day` | `enum` | 是   | 标准枚举值，见下表。                                                |
| `is_forced`   | `bool` | 否   | 默认 `false`。若为 `true`，Fountain 导出时在行首追加 `.` 强制标记。 |

**`time_of_day` 标准枚举** (英文，兼容 Fountain 国际惯例):

| 值           | 说明     | 中文映射             |
| ------------ | -------- | -------------------- |
| `DAY`        | 白天     | 白天、日、白昼       |
| `NIGHT`      | 夜晚     | 夜晚、夜里、夜       |
| `DAWN`       | 黎明     | 黎明、清晨、拂晓     |
| `DUSK`       | 黄昏     | 黄昏、傍晚、日落     |
| `LATER`      | 稍后     | 稍后、之后、片刻后   |
| `CONTINUOUS` | 连续时间 | 连续、紧接着         |
| `UNKNOWN`    | 未知     | (无法识别时的兜底值) |

> **自动映射规则**: LLM 输出中文时间词时，系统自动映射为上表对应的英文枚举值，原始中文值存入 `metadata.original_time` 以备审计。

### 5.6 `elements` — 剧本元素类型

元素是 YAML Schema 的**最小内容单元**。共定义 8 种元素类型，覆盖 Fountain 1.1 全部语法元素。

#### 5.6.1 元素类型总览

| `type`           | Fountain 对应        | 说明                             | 核心字段                                |
| ---------------- | -------------------- | -------------------------------- | --------------------------------------- |
| `action`         | Action               | 动作描述、场景叙述。             | `text`, `is_forced`, `is_centered`      |
| `dialogue_block` | Character + Dialogue | 对白逻辑块（角色+括号+台词）。   | `character_name`, `dialogue`, `is_dual` |
| `transition`     | Transition           | 转场指示。                       | `text`, `is_forced`                     |
| `lyric`          | Lyric                | 歌词/诗句。                      | `text`                                  |
| `boneyard`       | Boneyard             | 导演/编剧批注（原生 Fountain）。 | `text`                                  |
| `section`        | Section              | 幕/章节标记。                    | `text`, `level`                         |
| `synopsis`       | Synopsis             | 剧情概要。                       | `text`                                  |
| `page_break`     | Page Break           | 强制换页。                       | (无额外字段)                            |

#### 5.6.2 `action` — 动作描述

```yaml
- type: "action"
  text: "控制台上闪烁着微弱的红光。林明疲惫地靠在座椅上，手里把玩着一个旧式怀表。"
  is_forced: true # 对应 Fountain `!` 强制语法
  is_centered: false # 对应 Fountain `> text <` 居中语法
  source_ref:
      document_id: "doc_8f3a"
      chapter_id: "ch_02"
      offset: [1450, 1520]
```

| 字段          | 类型        | 必填 | 说明                                                |
| ------------- | ----------- | ---- | --------------------------------------------------- |
| `type`        | `"action"`  | 是   | 固定值。                                            |
| `text`        | `str`       | 是   | 动作描述文本。                                      |
| `is_forced`   | `bool`      | 否   | 默认 `false`。`true` → Fountain 导出行首加 `!`。    |
| `is_centered` | `bool`      | 否   | 默认 `false`。`true` → Fountain 导出为 `> text <`。 |
| `source_ref`  | `SourceRef` | 是   | 溯源锚点，详见 §6。                                 |

**Fountain 导出规则**:

- 默认: 直接输出 `text`。
- `is_forced`: 前缀 `!` 输出 `!{text}`。
- `is_centered`: 包裹为 `> {text} <`。

#### 5.6.3 `dialogue_block` — 对白逻辑块

将角色名、扩展标记、括号指示、对白内容及双人对话标记聚合为单个逻辑块。

```yaml
- type: "dialogue_block"
  character_id: "char_01"
  character_name: "林明"
  is_character_forced: true # 对应 Fountain `@` 强制语法
  character_extension: "(CONT'D)" # 精确保留作者输入, 系统绝不自动生成
  parenthetical: "(自嘲地笑)"
  dialogue: "你说，宇宙的边缘到底有什么？"
  is_dual: false # true → 导出时行尾加 `^` (双人对话)
  source_ref:
      document_id: "doc_8f3a"
      chapter_id: "ch_02"
      offset: [1521, 1545]
```

| 字段                  | 类型               | 必填 | 说明                                                            |
| --------------------- | ------------------ | ---- | --------------------------------------------------------------- |
| `type`                | `"dialogue_block"` | 是   | 固定值。                                                        |
| `character_id`        | `str`              | 是   | 角色 ID，必须可解析到 `characters[].id`。                       |
| `character_name`      | `str`              | 是   | 角色显示名（对应 Fountain 全大写行）。                          |
| `is_character_forced` | `bool`             | 否   | 默认 `false`。`true` → Fountain 导出角色名行首加 `@`。          |
| `character_extension` | `str` / `null`     | 否   | 角色扩展标记，如 `"(CONT'D)"`, `"(V.O.)"`, `"(O.S.)"`。         |
| `parenthetical`       | `str` / `null`     | 否   | 表演指导，需以 `(` 开头 `)` 结尾。                              |
| `dialogue`            | `str`              | 是   | 对白内容，不可为空。                                            |
| `is_dual`             | `bool`             | 否   | 默认 `false`。`true` → Fountain 导出 `dialogue` 行尾追加 ` ^`。 |
| `source_ref`          | `SourceRef`        | 是   | 溯源锚点，详见 §6。                                             |

**校验规则**:

- `character_id` 必须能解析到 `characters` 列表中的某个角色。
- `parenthetical` 若存在，必须以 `(` 开头、`)` 结尾。
- `character_extension` 必须以 `(` 开头 `)` 结尾（若存在）。
- `dialogue` 不允许为空字符串。

**Fountain 导出规则**:

```
@林明 (CONT'D)        ← is_character_forced + character_extension
(自嘲地笑)             ← parenthetical
你说，宇宙的边缘到底有什么？ ^  ← dialogue + is_dual
```

> **⚠️ 设计铁律**: `character_extension` 字段**严禁由系统自动生成**。它仅作为 LLM 提取或人工编辑的原文载体。系统绝不根据上下文自动插入 `(CONT'D)`——这属于作者创作域，不可越界。

#### 5.6.4 `transition` — 转场指示

```yaml
- type: "transition"
  text: "CUT TO:"
  is_forced: false # true → 导出时前缀加 `>`
  source_ref: null # 转场常为剧本构造, 可无溯源
```

| 字段         | 类型               | 必填 | 说明                                     |
| ------------ | ------------------ | ---- | ---------------------------------------- |
| `type`       | `"transition"`     | 是   | 固定值。                                 |
| `text`       | `str`              | 是   | 转场文本，推荐全大写英文 + `:` 结尾。    |
| `is_forced`  | `bool`             | 否   | 默认 `false`。`true` → 导出加 `>` 前缀。 |
| `source_ref` | `SourceRef`/`null` | 否   | 若 LLM 可从原文推导则注入。              |

**Fountain 导出规则**:

- `is_forced = true`: `>{text}`
- `is_forced = false` 且以 `:` 结尾: 直接输出，Fountain 根据 `:` 自动识别。
- `is_forced = false` 且不以 `:` 结尾: 追加 `>` 前缀。

#### 5.6.5 `lyric` — 歌词/诗句

```yaml
- type: "lyric"
  text: "星空下的低语，穿越亿万光年的距离..."
  source_ref: null
```

| 字段         | 类型               | 必填 | 说明       |
| ------------ | ------------------ | ---- | ---------- |
| `type`       | `"lyric"`          | 是   | 固定值。   |
| `text`       | `str`              | 是   | 歌词内容。 |
| `source_ref` | `SourceRef`/`null` | 否   | 溯源锚点。 |

**Fountain 导出规则**: 行首加 `~` 前缀: `~ 星空下的低语...`。

#### 5.6.6 `boneyard` — 批注（Fountain 原生）

```yaml
- type: "boneyard"
  text: "导演注：此处建议增加特写镜头，表现怀表上刻着的名字。"
```

| 字段   | 类型         | 必填 | 说明                                     |
| ------ | ------------ | ---- | ---------------------------------------- |
| `type` | `"boneyard"` | 是   | 固定值。替代初版中的非标准 `note` 类型。 |
| `text` | `str`        | 是   | 批注内容，支持多行文本。                 |

**Fountain 导出规则**: 包裹为 `/* {text} */`，多行批注跨行保留。

> **命名变更说明**: v1.0.0 使用 `note` 类型——这是自定义扩展，不符合 Fountain 规范。v2.0.0 改用 `boneyard`，与 Fountain 1.1 原生 Boneyard (`/* */`) 语法一一对应。

#### 5.6.7 `section` — 章节/幕标记

```yaml
- type: "section"
  text: "第一幕：深空"
  level: 1 # 1=#, 2=##, 3=###, 4=####
```

| 字段    | 类型        | 必填 | 说明                   |
| ------- | ----------- | ---- | ---------------------- |
| `type`  | `"section"` | 是   | 固定值。               |
| `text`  | `str`       | 是   | 章节/幕标题。          |
| `level` | `int`       | 是   | 1-4，对应 `#`–`####`。 |

**Fountain 导出规则**: 输出为 `{level 个 #} {text}`，如 `# 第一幕：深空`。

#### 5.6.8 `synopsis` — 剧情概要

```yaml
- type: "synopsis"
  text: "林明陷入对地球时代的回忆。"
```

| 字段   | 类型         | 必填 | 说明       |
| ------ | ------------ | ---- | ---------- |
| `type` | `"synopsis"` | 是   | 固定值。   |
| `text` | `str`        | 是   | 概要内容。 |

**Fountain 导出规则**: 行首加 `=` 前缀: `= 林明陷入对地球时代的回忆。`

#### 5.6.9 `page_break` — 强制换页

```yaml
- type: "page_break"
```

| 字段   | 类型           | 必填 | 说明     |
| ------ | -------------- | ---- | -------- |
| `type` | `"page_break"` | 是   | 固定值。 |

**Fountain 导出规则**: 输出 `===`。无额外字段，元素本身即为分页信号。

## 6. 溯源机制深度设计

### 6.1 `source_ref` — 三维锚点

```yaml
source_ref:
    document_id: "doc_8f3a" # 必填。原始文档 ID, 指向 tasks 表或文件 Hash
    chapter_id: "ch_02" # 必填。章节标识
    offset: [1450, 1520] # 必填。左闭右开字符区间 [start, end)
```

| 字段          | 类型         | 必填 | 说明                                                    |
| ------------- | ------------ | ---- | ------------------------------------------------------- |
| `document_id` | `str`        | 是   | 全局溯源根 ID，支持 SRS 定义的多文件上传/网页抓取场景。 |
| `chapter_id`  | `str`        | 是   | 章节唯一 ID，对应 `chapters` 表中记录。                 |
| `offset`      | `[int, int]` | 是   | 长度为 2 的整数数组，`[start, end)`，Python 切片风格。  |

### 6.2 溯源工作流

```
前端点击对白 → 解析 source_ref → 查询对应章节 & offset → 左栏原文滚动定位 → 黄色高亮
          ← 左栏选中原文段落 → 查询引用该 offset 的 Element → 中栏/右栏同步高亮
```

### 6.3 防漂移校验

在生成 YAML 后，系统必须在后台**静默执行抽样校验**:

```python
# 伪代码
expected = original_text[source_ref.offset[0] : source_ref.offset[1]]
actual = element.text  # 或 element.dialogue
if not fuzzy_match(expected, actual):
    system_meta.warnings.append(
        f"Offset Drift: {source_ref.chapter_id}[{source_ref.offset}] "
        f"expected '{expected[:30]}...' but got '{actual[:30]}...'"
    )
```

- 偏移漂移不阻塞管道（LLM 改写不可避免），但必须记录在 `system_meta.warnings` 中。
- 前端可通过警告图标提示用户该元素的溯源可能不精确。

### 6.4 多对一映射

若 LLM 将原文多处信息融合为一个 Element:

- `source_ref` 指向**核心主旨**所在的原文区间（主引用）。
- 次要引用放入 `metadata.additional_refs` 数组:

```yaml
metadata:
    additional_refs:
        - { document_id: "doc_8f3a", chapter_id: "ch_02", offset: [1800, 1830] }
        - { document_id: "doc_8f3a", chapter_id: "ch_03", offset: [200, 250] }
```

## 7. 格式转换矩阵

### 7.1 YAML → Fountain 1.1 (前向导出)

此矩阵是 `yaml_serializer.py` 的核心逻辑规范。

| YAML 节点                                    | Fountain 1.1 序列化规则                                     |
| :------------------------------------------- | :---------------------------------------------------------- |
| `title_page`                                 | 逐行 `Key: Value`，多行 `Contact` 缩进 4 空格，以空行结束。 |
| `system_meta`                                | **不导出**——仅驻留在 YAML/JSON 内部。                       |
| `heading.is_forced == true`                  | 输出 `. {heading.text or int_ext. location - time_of_day}`  |
| `heading.is_forced == false`                 | 输出 `{heading.text or 重建自结构化字段}`                   |
| `action.is_forced == true`                   | 输出 `! {text}`                                             |
| `action.is_centered == true`                 | 输出 `> {text} <`                                           |
| `action` (默认)                              | 直接输出 `{text}`                                           |
| `dialogue_block.is_character_forced == true` | 输出 `@{character_name}{character_extension}`               |
| `dialogue_block` (默认)                      | 输出 `{CHARACTER_NAME}{character_extension}` (全大写)       |
| `dialogue_block.parenthetical`               | 下一行输出 `{parenthetical}`                                |
| `dialogue_block.dialogue`                    | 下一行输出 `{dialogue}`                                     |
| `dialogue_block.is_dual == true`             | `dialogue` 行尾追加 ` ^`                                    |
| `transition.is_forced == true`               | 输出 `> {text}`                                             |
| `transition` (默认, 以 `:` 结尾)             | 直接输出 `{text}` (Fountain 自动识别)                       |
| `transition` (默认, 不以 `:` 结尾)           | 输出 `> {text}`                                             |
| `lyric`                                      | 输出 `~ {text}`                                             |
| `boneyard`                                   | 输出 `/* {text} */` (支持多行)                              |
| `section`                                    | 输出 `{level个#} {text}`                                    |
| `synopsis`                                   | 输出 `= {text}`                                             |
| `page_break`                                 | 输出 `===`                                                  |

### 7.2 Fountain 1.1 → YAML (逆向解析)

此矩阵确保 `.fountain` 文件可被完整逆向重建为 YAML Schema。

| Fountain 语法                  | 逆向解析策略                                                     |
| :----------------------------- | :--------------------------------------------------------------- |
| Title Page `Key: Value` 键值块 | 正则 `^([A-Za-z ]+):\s*(.*)$`，识别到连续空行结束。              |
| `.` 前缀场标 (非 `..` 省略号)  | `heading.is_forced = true`, 解析 `int_ext`, `location`, `time`。 |
| `!` 前缀 Action                | `action.is_forced = true`, 其余为 `text`。                       |
| `@` 前缀角色名                 | `dialogue_block.is_character_forced = true`。                    |
| `角色名 (EXT)`                 | 正则提取 `character_name` 与 `character_extension`。             |
| `(parenthetical)` 独立行       | 归纳到最近的上一个 `dialogue_block.parenthetical`。              |
| 行尾 ` ^`                      | `dialogue_block.is_dual = true`。                                |
| `~` 前缀                       | 创建 `type: "lyric"`。                                           |
| `> ` 前缀转场                  | `transition.is_forced = true`。                                  |
| 全大写 `:` 结尾行（非角色名）  | 创建 `type: "transition"`, `is_forced = false`。                 |
| `/* ... */` 闭合               | 创建 `type: "boneyard"`，支持跨行。                              |
| `#` / `##` / `###` / `####` 行 | 创建 `type: "section"`, `level = #数量`。                        |
| `=` 前缀                       | 创建 `type: "synopsis"`。                                        |
| `===`                          | 创建 `type: "page_break"`。                                      |
| `> text <` (居中)              | `action.is_centered = true`。                                    |
| 空行                           | 元素边界分隔符。                                                 |

## 8. Pydantic V2 模型

### 8.1 核心模型定义

```python
from pydantic import BaseModel, Field, model_validator
from typing import Optional, Literal, Union
from enum import Enum
from datetime import datetime


class TimeOfDay(str, Enum):
    DAY = "DAY"
    NIGHT = "NIGHT"
    DAWN = "DAWN"
    DUSK = "DUSK"
    LATER = "LATER"
    CONTINUOUS = "CONTINUOUS"
    UNKNOWN = "UNKNOWN"


class IntExt(str, Enum):
    INT = "INT"
    EXT = "EXT"
    INT_EXT = "INT/EXT"
    EST = "EST"


class SourceRef(BaseModel):
    document_id: str = Field(min_length=1)
    chapter_id: str = Field(min_length=1)
    offset: tuple[int, int]  # [start, end), 左闭右开

    @model_validator(mode="after")
    def check_offset_order(self):
        if self.offset[0] >= self.offset[1]:
            raise ValueError(f"offset start must be < end, got {self.offset}")
        return self


class TitlePage(BaseModel):
    Title: str
    Credit: Optional[str] = None
    Author: str
    Source: Optional[str] = None
    Draft_date: Optional[str] = Field(None, alias="Draft date")
    Contact: Optional[str] = None
    Notes: Optional[str] = None

    model_config = {"populate_by_name": True}


class SystemMeta(BaseModel):
    document_id: str = Field(min_length=1)
    model: Literal["deepseek-v4-pro", "deepseek-v4-flash"]
    timestamp: datetime
    schema_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    language: str = "zh-CN"
    source_word_count: Optional[int] = None
    warnings: list[str] = Field(default_factory=list)


class Heading(BaseModel):
    text: str
    int_ext: Optional[IntExt] = None
    location: str
    time_of_day: TimeOfDay = TimeOfDay.UNKNOWN
    is_forced: bool = False


class Character(BaseModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)
    description: str
    metadata: dict = Field(default_factory=dict)


class ActionElement(BaseModel):
    type: Literal["action"]
    text: str
    is_forced: bool = False
    is_centered: bool = False
    source_ref: SourceRef


class DialogueBlock(BaseModel):
    type: Literal["dialogue_block"]
    character_id: str
    character_name: str
    is_character_forced: bool = False
    character_extension: Optional[str] = None
    parenthetical: Optional[str] = None
    dialogue: str = Field(min_length=1)
    is_dual: bool = False
    source_ref: SourceRef

    @model_validator(mode="after")
    def check_parenthetical_format(self):
        if self.parenthetical and not (
            self.parenthetical.startswith("(") and self.parenthetical.endswith(")")
        ):
            raise ValueError(
                f"parenthetical must be wrapped in (): {self.parenthetical}"
            )
        return self

    @model_validator(mode="after")
    def check_extension_format(self):
        if self.character_extension and not (
            self.character_extension.startswith("(")
            and self.character_extension.endswith(")")
        ):
            raise ValueError(
                f"character_extension must be wrapped in (): {self.character_extension}"
            )
        return self


class TransitionElement(BaseModel):
    type: Literal["transition"]
    text: str
    is_forced: bool = False
    source_ref: Optional[SourceRef] = None


class LyricElement(BaseModel):
    type: Literal["lyric"]
    text: str
    source_ref: Optional[SourceRef] = None


class BoneyardElement(BaseModel):
    type: Literal["boneyard"]
    text: str


class SectionElement(BaseModel):
    type: Literal["section"]
    text: str
    level: int = Field(ge=1, le=4)


class SynopsisElement(BaseModel):
    type: Literal["synopsis"]
    text: str


class PageBreakElement(BaseModel):
    type: Literal["page_break"]


# 联合类型: 8 种 Element
ScriptElement = Union[
    ActionElement,
    DialogueBlock,
    TransitionElement,
    LyricElement,
    BoneyardElement,
    SectionElement,
    SynopsisElement,
    PageBreakElement,
]


class Scene(BaseModel):
    scene_id: str = Field(min_length=1)
    heading: Heading
    characters_present: list[str] = Field(default_factory=list)
    elements: list[ScriptElement] = Field(min_length=1)
    source_ref: Optional[SourceRef] = None
    metadata: dict = Field(default_factory=dict)


class GraphNode(BaseModel):
    id: str
    label: str
    type: Literal[
        "character", "location", "prop", "event", "organization", "concept"
    ]
    metadata: dict = Field(default_factory=dict)


class GraphEdge(BaseModel):
    source: str
    target: str
    relation: str
    weight: float = Field(ge=0.0, le=1.0, default=0.5)

    @model_validator(mode="after")
    def check_self_loop(self):
        if self.source == self.target:
            raise ValueError(f"Edge cannot be a self-loop: {self.source}")
        return self


class KnowledgeGraph(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class Script(BaseModel):
    title_page: TitlePage
    system_meta: SystemMeta
    summary: str = Field(max_length=500)
    characters: list[Character]
    scenes: list[Scene]
    knowledge_graph: KnowledgeGraph
```

### 8.2 文件组织建议

```
backend/
├── app/
│   ├── models/
│   │   ├── __init__.py
│   │   ├── script.py             # Script, ScriptElement (Union)
│   │   ├── meta.py               # TitlePage, SystemMeta
│   │   ├── heading.py            # Heading, TimeOfDay, IntExt
│   │   ├── character.py          # Character
│   │   ├── scene.py              # Scene
│   │   ├── elements.py           # ActionElement, DialogueBlock, TransitionElement, ...
│   │   ├── source_ref.py         # SourceRef
│   │   ├── knowledge_graph.py    # GraphNode, GraphEdge, KnowledgeGraph
│   │   └── http.py               # BaseResponse, ErrorResponse
│   ├── services/
│   │   ├── yaml_serializer.py    # YAML ↔ Fountain ↔ JSON 转换器
│   │   ├── fountain_parser.py    # Fountain → YAML 逆向解析器
│   │   └── validator.py          # 三级校验与 Auto-Fix 引擎
│   └── ...
└── tests/
    ├── test_yaml_serializer.py
    ├── test_fountain_parser.py
    ├── test_validator.py
    └── fixtures/
        ├── sample_script.yaml
        └── sample_script.fountain
```

## 9. 校验与容错策略

### 9.1 三级校验链

```
LLM 输出 (raw JSON/YAML)
    │
    ▼
┌──────────────────────────────┐
│  Level 1: Pydantic 结构校验   │  ← 必填字段、类型检查、枚举匹配、正则约束
│  (ValidationError 捕获)       │
└──────────┬───────────────────┘
           │ 通过?
           ▼
┌──────────────────────────────┐
│  Level 2: 语义引用校验        │  ← character_id 可解析, scene_id 唯一
│  (自定义 validator)           │     source_ref 字段完整性, edge 端点存在
└──────────┬───────────────────┘
           │ 通过?
           ▼
┌──────────────────────────────┐
│  Level 3: 往返转换校验        │  ← YAML → Fountain → YAML 无损验证
│  (round-trip test)           │     抽样比对关键字段一致性
└──────────────────────────────┘
```

### 9.2 校验与重试流程

1. `LangChain` `JsonOutputParser` + Pydantic `model_validate()` 双阶段校验。
2. 校验通过的 Scene 进入 `source_ref` 注入（exact→prefix→estimated 三级回退）。
3. 网络/超时/限流错误由 `invoke_with_retry()` 自动使用指数退避重试（每阶段 1-3 次可配）。
4. 不可恢复的错误（格式非法/模型幻觉）→ 降级策略：丢弃非法 Element，当前阶段回退（转换→空列表，优化→保留原始场景）。
5. Pipeline 各阶段独立回退，任意阶段失败不阻断下游。

### 9.3 系统自动修复规则 (无需 LLM)

部分格式错误可由系统直接修正（不消耗 LLM 调用）:

| 场景                                 | 修复规则                                                        |
| ------------------------------------ | --------------------------------------------------------------- |
| `parenthetical` 缺少括号             | 自动包裹: `"低声"` → `"(低声)"`                                 |
| `character_extension` 缺少括号       | 自动包裹: `"CONT'D"` → `"(CONT'D)"`                             |
| `time_of_day` 中文输入               | 查表映射: `"夜晚"` → `NIGHT`，原始值存 `metadata.original_time` |
| `weight` 越界                        | Clamp 到 `[0.0, 1.0]`                                           |
| `aliases` 含空字符串                 | 过滤移除                                                        |
| `dialogue_block` 缺少 `character_id` | 尝试通过 `character_name` 模糊匹配角色列表                      |

## 10. 版本策略

### 10.1 Schema 语义版本

Schema 版本号存储在 `system_meta.schema_version`，独立于项目版本，遵循 SemVer:

- **MAJOR**: 破坏性变更（字段重命名、移除、结构重组）。例如 v1→v2 的 `note`→`boneyard`, `dialogue`→`dialogue_block`。
- **MINOR**: 向后兼容的新增（新 Element 类型、新可选字段、枚举值补充）。
- **PATCH**: 文档修正、描述更新、校验规则微调。

### 10.2 迁移兼容

- 读取旧版 YAML/JSON 时，检测 `system_meta.schema_version`，若 MAJOR 不匹配则运行迁移函数。
- 数据库 `script_json` 列始终存储**最新版本** Schema。
- 前端 Monaco Editor 在打开旧版文件时显示 "Schema 已升级，建议重新导出" 提示。

## 11. 完整剧本示例

以下示例覆盖了所有 8 种元素类型及 Fountain 1.1 强制语法特性：

```yaml
script:
    title_page:
        Title: "星辰低语"
        Credit: "改编"
        Author: "NovelScript AI"
        Source: "原著: 刘慈欣"
        Draft date: "2026-06-05"
        Contact: |
            NovelScript Studio
            contact@novelscript.ai
    system_meta:
        document_id: "doc_8f3a"
        model: "deepseek-v4-pro"
        timestamp: "2026-06-05T12:00:00Z"
        schema_version: "2.0.0"
        language: "zh-CN"
        source_word_count: 15234
        warnings: []
    summary: "在废弃的星际飞船上，颓废的领航员林明与冷酷的仿生人艾娃展开了一场关于宇宙边缘与人类情感的对话。"
    characters:
        - id: "char_01"
          name: "林明"
          aliases: ["老林", "领航员"]
          description: "30岁，颓废的星际领航员，右眼有机械义眼。"
          metadata: {}
        - id: "char_02"
          name: "艾娃"
          aliases: []
          description: "AI 仿生人，冷静，缺乏人类情感。"
          metadata: {}
    scenes:
        - scene_id: "S001"
          heading:
              text: "内景. 废弃飞船驾驶舱 - 夜晚"
              int_ext: "INT"
              location: "废弃飞船驾驶舱"
              time_of_day: "NIGHT"
              is_forced: false
          characters_present: ["char_01", "char_02"]
          source_ref:
              document_id: "doc_8f3a"
              chapter_id: "ch_02"
              offset: [1400, 1850]
          metadata:
              estimated_duration_sec: 120
              tone: "压抑、忧伤"
          elements:
              - type: "section"
                text: "第一幕：深空"
                level: 1
              - type: "synopsis"
                text: "林明陷入对地球时代的回忆。"
              - type: "action"
                text: "控制台上闪烁着微弱的红光。林明疲惫地靠在座椅上，手里把玩着一个旧式怀表。艾娃静静地站在他身后。"
                is_forced: true
                is_centered: false
                source_ref:
                    document_id: "doc_8f3a"
                    chapter_id: "ch_02"
                    offset: [1450, 1520]
              - type: "dialogue_block"
                character_id: "char_01"
                character_name: "林明"
                is_character_forced: true
                character_extension: "(CONT'D)"
                parenthetical: "(自嘲地笑)"
                dialogue: "你说，宇宙的边缘到底有什么？"
                is_dual: false
                source_ref:
                    document_id: "doc_8f3a"
                    chapter_id: "ch_02"
                    offset: [1521, 1545]
              - type: "dialogue_block"
                character_id: "char_02"
                character_name: "艾娃"
                is_character_forced: false
                character_extension: null
                parenthetical: "(机械音，毫无波澜)"
                dialogue: "根据目前的物理模型，只有无尽的真空和辐射。"
                is_dual: true
                source_ref:
                    document_id: "doc_8f3a"
                    chapter_id: "ch_02"
                    offset: [1546, 1580]
              - type: "lyric"
                text: "星空下的低语，穿越亿万光年的距离..."
                source_ref: null
              - type: "boneyard"
                text: "导演注：此处建议增加特写镜头，表现怀表上刻着的名字。"
              - type: "transition"
                text: "CUT TO:"
                is_forced: false
                source_ref: null
              - type: "page_break"
    knowledge_graph:
        nodes:
            - id: "char_01"
              label: "林明"
              type: "character"
            - id: "char_02"
              label: "艾娃"
              type: "character"
            - id: "loc_01"
              label: "废弃飞船驾驶舱"
              type: "location"
            - id: "item_01"
              label: "旧式怀表"
              type: "prop"
        edges:
            - source: "char_01"
              target: "char_02"
              relation: "主仆/同伴"
              weight: 0.8
            - source: "char_01"
              target: "loc_01"
              relation: "所在"
              weight: 1.0
            - source: "char_01"
              target: "item_01"
              relation: "持有"
              weight: 0.9
```

## 12. 扩展预留

所有扩展均通过 `metadata` 字段承载，不破坏现有 Schema 结构。

| 扩展项             | 影响范围                  | 说明                                                                                                                                                                                                      |
| ------------------ | ------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **镜头/机位**      | `scenes[].metadata`       | 存储 `shot_type`, `camera_angle` 等分镜信息。                                                                                                                                                             |
| **情绪标记**       | `dialogue_block.metadata` | 存储 `emotion: "愤怒"` 供 TTS 朗读使用。                                                                                                                                                                  |
| **时间轴**         | `scenes[].metadata`       | 存储 `story_time: "第3天 14:00"` 供时间线可视化。                                                                                                                                                         |
| **多语言对白**     | `dialogue_block.metadata` | 存储 `translations: { en: "..." }`。                                                                                                                                                                      |
| **BGM / 音效**     | `scenes[].elements[]`     | 新增 `type: "sound"` 元素。                                                                                                                                                                               |
| **场景气氛图 URL** | `scenes[].metadata`       | 存储 `concept_art_url`。                                                                                                                                                                                  |
| **修订历史**       | `system_meta`             | 存储 `revision_history: [{timestamp, author, summary}]`。                                                                                                                                                 |
| **叙事类型标记**   | `elements[].metadata`     | 存储 `narrative_type: "flashback" \| "flashforward" \| "voice_over" \| "internal_monologue" \| "dream_sequence" \| "montage" \| "letter" \| "default"`，标记元素的叙事模式。默认 `"default"` 为线性叙述。 |
| **时间线 ID**      | `scenes[].metadata`       | 存储 `timeline_id: "T1"` 与 `timeline_label: "主线"`，支持多时间线可视化与交叉剪辑重组。同时支持元素级 `timeline_id` 覆盖（存于 `elements[].metadata`）。                                                 |
| **画外音来源**     | `dialogue_block.metadata` | 存储 `vo_source: "narrator" \| "character_self" \| "external" \| "archival"`，区分客观旁白 / 角色内心独白 / 外部声音 / 档案录音。需配合 `character_extension: "(V.O.)"` 使用。                            |
| **闪回区间**       | `scenes[].metadata`       | 存储 `flashback_range: { from: "第3天 14:00", to: "第3天 14:05" }`，标记闪回的时间跨度，供前端时间线可视化渲染。                                                                                          |
| **叙事层级**       | `scenes[].metadata`       | 存储 `narrative_layer: "present" \| "past" \| "future" \| "imaginary" \| "parallel"`，区分当前叙事层级，解决长篇小说改编中常见的多层叙事嵌套问题。                                                        |

## 13. 参考

- [Fountain 1.1 Specification](https://fountain.io/syntax/)
- [YAML 1.2.2 Specification](https://yaml.org/spec/1.2.2/)
- [JSON Patch RFC 6902](https://datatracker.ietf.org/doc/html/rfc6902)
- [Semantic Versioning 2.0.0](https://semver.org/lang/zh-CN/)
- [SRS 需求规格说明书](./SRS%20需求规格说明书.md) §6.1–§6.4
- [Development References](./dev_references.md)
- [Fountain 1.1 市场地位与价值评估报告](../reports/边缘化的选择：Fountain%201.1%20在全球小说改编剧本行业的地位与价值评估.pdf)
