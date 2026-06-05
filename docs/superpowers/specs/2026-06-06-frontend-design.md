# NovelScript 前端界面设计说明书

- **项目名称**：NovelScript (析幕) — 前端工作台
- **文档版本**：v1.0.0
- **日期**：2026-06-06
- **作者**：Dinosaur_MC
- **关联文档**：[SDS 软件设计说明书](../SDS%20软件设计说明书.md) · [SRS 需求规格说明书](../SRS%20需求规格说明书.md) · [YAML Schema 设计说明](../YAML_Schema_设计说明.md)
- **参考报告**：[解构三大主流UI范式：NovelScript 的布局、交互与定制化设计优化路径](../../reports/解构三大主流UI范式：NovelScript%20(析幕)%20的布局、交互与定制化设计优化路径.pdf)

---

## 1. 设计概述

### 1.1 定位

本文档是 NovelScript 前端工作台的**面向实施的 UI/UX 设计规范**，覆盖 MVP（72h）范围内的组件树、状态管理、数据流、路由设计、Design Tokens、API Client 封装与测试策略。文档可直接指导开发团队开始编码。

### 1.2 设计目标

| 目标 | 约束条件 |
|---|---|
| **三栏 IDE 工作台** | 左栏 TipTap 原文阅读 + 中栏 Monaco YAML 编辑 + 右栏预览/图谱/AI Tab |
| **双向溯源联动** | source_ref 驱动的毫秒级原文↔剧本高亮跳转 |
| **AI 辅助编辑** | 上下文感知对话 + JSON Patch 生成/应用/撤销 |
| **72h 可交付** | 方案在 SDS 基础上做最小必要增强（Hooks 抽象层 + 非受控 Monaco） |

### 1.3 技术栈确认

| 层 | 技术选型 |
|---|---|
| **框架** | React 19 + TypeScript + Vite |
| **路由** | React Router v7 (SSR) |
| **状态管理** | Zustand (5 stores) |
| **UI 库** | Ant Design 6 + Tailwind CSS 4 |
| **原文阅读** | TipTap (StarterKit + Highlight extension) |
| **代码编辑** | Monaco Editor (非受控模式) |
| **知识图谱** | ReactFlow |
| **图标** | @ant-design/icons |

### 1.4 设计原则

- **非受控 Monaco** — 用户键入在 Monaco 内部 buffer，只在保存/外部写入时与 store 同步，避免大 YAML 卡顿
- **Hooks 命令式桥接** — stores 只存可序列化状态；DOM 实例（TipTap ref、Monaco ref）通过 custom hooks 命令式操作
- **单向数据流** — 用户操作 → Hook → API → Store → React 重渲染
- **面板解耦** — 三栏不直接通信，通过 `useTraceLinking` 协调溯源联动

---

## 2. 布局系统与组件树

### 2.1 顶层布局

```
┌──────────────────────────────────────────────────────────┐
│  <TaskBar>  Logo │ 任务状态指示灯 │ 导出 ▾ │ 用户头像    │  h-12
├──────────────────────────────────────────────────────────┤
│                    <ThreePanelLayout>                     │
│  ┌──────────┬──────────────────┬──────────────────────┐  │
│  │          │                  │  ┌─Tab1──Tab2──Tab3┐ │  │
│  │ 左栏     │  中栏            │  │ 预览 / 图谱/ AI  │ │  │
│  │ TipTap   │  Monaco Editor   │  │                  │ │  │
│  │ 原文阅读  │  YAML 编辑       │  │  Tab 内容区       │ │  │
│  │ 28-32%   │  38-44%          │  │  28-32%          │ │  │
│  └──────────┴──────────────────┴──────────────────────┘  │
├──────────────────────────────────────────────────────────┤
│  <StatusBar>  进度条 ████████░░ 65% │ SSE 日志滚动        │  h-8
└──────────────────────────────────────────────────────────┘
```

### 2.2 面板宽度

- CSS `calc()` + CSS 变量驱动，拖拽手柄（4px 宽 `Splitter` 组件）调整
- 宽度存入 `ui-store`（仅存百分比数字），`localStorage` 持久化
- 最小宽度硬限制：左栏 240px、中栏 360px、右栏 280px
- 拖拽走 `requestAnimationFrame` 避免频繁 reflow

### 2.3 组件树

```
<App>
  <TaskBar />                    ← task-store (status, progress)
  <ThreePanelLayout>
    <Splitter direction="vertical">
      <NovelReader />            ← novel-store + useNovelReader + useTraceLinking
      <Splitter direction="vertical">
        <ScriptEditor />         ← script-store + editor-store + useScriptEditor
        <RightPanel>
          <Tabs activeTab={uiStore.activeTab}>
            <ScriptPreview />    ← Tab 1: 剧本可视化预览
            <KnowledgeGraph />   ← Tab 2: ReactFlow 知识图谱
            <AIChat />           ← Tab 3: AI 对话面板
          </Tabs>
        </RightPanel>
      </Splitter>
    </Splitter>
  </ThreePanelLayout>
  <StatusBar />                  ← task-store (progress)
</App>
```

### 2.4 布局原则

- **Ant Design 6** 提供基础 UI（Tabs、Button、Dropdown、Progress、Spin、Message、Skeleton）
- **Tailwind CSS 4** 处理间距、颜色、响应式微调
- 不引入额外布局库 — Ant Design Flex/Row/Col 配合 Tailwind 够用
- Splitter 用经典 alligator.io 实现（~60 行 CSS + React ref 拖拽逻辑，不依赖 npm 包）
- RightPanel Tab 切换用 CSS `display:none` 而非条件渲染，保留各 Tab 内部状态

---

## 3. 状态管理架构

### 3.1 方案选择

采用 **Hooks 抽象层 + Stores 瘦身**（方案二）——在 SDS 规划的 4 个 Zustand store 基础上增加 `novel-store` 补齐原文数据归属，并新增 6 个 custom hooks 层做命令式 DOM 操作。

### 3.2 Store 职责表

| Store | 核心字段 | 类型 | 用途 |
|---|---|---|---|
| **task-store** | `taskId`, `novelId`, `status`, `progress`(0-100), `errorMessage` | 可序列化 | 任务生命周期 |
| **novel-store** | `novelId`, `title`, `chapters[]`({index, title, content}), `selectedChapterId` | 可序列化 | 原文数据与阅读导航 |
| **script-store** | `yaml`(string), `scenes[]`, `characters[]`, `sourceRefMap`(Map) | 可序列化 | 剧本数据 + 溯源索引 |
| **editor-store** | `undoStack[]`(Patch[]), `redoStack[]`(Patch[]), `dirty`(boolean), `validationErrors[]` | 可序列化 | 编辑器 undo/redo 栈 |
| **ui-store** | `leftWidth`, `centerWidth`, `rightWidth`(number), `activeTab`('preview'\|'graph'\|'chat') | 可序列化 | UI 布局状态 |

### 3.3 Custom Hooks

```
hooks/
├── useNovelReader.ts     # TipTap 实例 ref，段落高亮/滚动 API
├── useScriptEditor.ts    # Monaco 实例 ref (非受控)，getValue/setValue/undo/redo
├── useTraceLinking.ts    # 双向溯源核心: 监听 click → 查 sourceRefMap → 驱动对方面板
├── useSSE.ts             # EventSource 订阅 + 轮询 fallback
├── useAutoSave.ts        # 防抖 YAML 保存 (PUT /api/v1/scripts/{id})
└── useKeyboard.ts        # 全局快捷键 (Ctrl+S 保存, Ctrl+Z/Y 委托给 Monaco)
```

### 3.4 数据流规则

```
用户操作 → Hook 命令式 API → 写 Store（序列化状态）
                ↓
          API 调用（SSE / REST）
                ↓
          Store 更新 → React 重渲染受影响组件

Monaco 数据流（关键）：非受控模式
  写入：用户键入 → Monaco 内部 buffer
        保存(Ctrl+S) → useScriptEditor.getMonacoValue() → PUT API
         → 成功后 → script-store.setYaml() + editor-store.clearDirty()
  读取：script-store.yaml 更新（AI Patch 应用后）
         → useScriptEditor.setMonacoValue() 命令式写入
```

### 3.5 跨面板通信

不引入 EventBus。三个面板通过 `useTraceLinking` hook 协调：

- **点击剧本元素（右栏/中栏）** → hook 读 `sourceRefMap[elementId]` → 调 `useNovelReader.scrollToOffset(offset)`
- **点击原文段落（左栏）** → hook 查 `sourceRefMap` 反查 → 调 `useScriptEditor.highlightLine()` + 右栏高亮
- 每个 hook 持有对应组件的 `ref`，不依赖全局事件

---

## 4. 双向溯源交互设计

### 4.1 前向追溯（剧本 → 原文）

```
右栏/中栏点击 Element
  → 从 script-store.sourceRefMap 获取 {chapter_id, offset}
  → 若 chapter_id 非当前选中章节 → novel-store.setSelectedChapter(chapter_id)
  → useNovelReader.scrollToOffset(offset) + 临时黄色高亮 (2s 渐隐)
```

### 4.2 后向追溯（原文 → 剧本）

```
左栏选中原文段落（拖选 / 双击）
  → useTraceLinking 获取选区 [start, end] offset
  → 遍历 script-store.sourceRefMap，找出 offset 区间有交集的 element_ids
  → useScriptEditor.highlightLines(elementIds)
  → 右栏 ScriptPreview 同步添加高亮标记
```

### 4.3 高亮策略

| 面板 | 高亮方式 | 持续时间 |
|---|---|---|
| 左栏 TipTap | `Highlight` extension, 黄色背景 `rgba(253,203,110,0.35)` (trace-source-bg) | 2s 渐隐，点击后留 30s 淡色锚点标记 |
| 中栏 Monaco | `deltaDecorations` API, 行号左侧蓝色竖条 (`#74b9ff`, trace-marker) | 直到下次操作 |
| 右栏 Preview | React state 控制, 紫色边框 + 浅色底 | 与中栏同步清除 |

### 4.4 性能边界

- `sourceRefMap` 用 `Map<string, SourceRef>` (O(1) 正向查)
- 反向查（offset → element）需遍历 — 场景数 < 200 时 O(n) 可接受，超过则建 interval tree
- Monaco `deltaDecorations` 批量调用，不在 `mousemove` 中触发
- 拖拽调整面板宽度时走 `requestAnimationFrame`

### 4.5 API 依赖

- `sourceRefMap` 由 `GET /api/v1/tasks/{id}` 返回的 `script_json` 中 client-side 构建
- 不需要额外的溯源查询 endpoint — 数据已在剧本 JSON 中完整携带

---

## 5. 面板组件规格

### 5.1 NovelReader（左栏 — TipTap）

**Props / Inputs**: `chapters[]` (from novel-store), `selectedChapterId`

**功能清单**:
- 渲染当前章节纯文本（非富文本，TipTap 仅作阅读器 + 选区高亮载体）
- 章节下拉切换（Ant Design Select，联动 novel-store.selectedChapterId）
- 段落级可点击：双击/拖选 → 触发后向溯源（`useTraceLinking`）
- 收到 `scrollToOffset` 调用 → 平滑滚动到指定位置 + 高亮
- 搜索定位（Ctrl+F，Ant Input.Search，在 TipTap 内容中查找并跳转）

**TipTap Extensions**:
```
StarterKit (仅 heading, paragraph, text — 关闭 bold/italic 等富文本)
+ Highlight (黄色临时标记)
+ Placeholder (无内容时显示 "请上传小说...")
```

### 5.2 ScriptEditor（中栏 — Monaco）

**Props / Inputs**: `yaml` (initial value from script-store), `validationErrors[]`

**功能清单**:
- YAML 语法高亮（Monaco 内置 yaml language）
- 错误波浪线：读取 `editor-store.validationErrors[]` → `setModelMarkers()` 在对应行显示红色波浪线
- Ctrl+S → `useAutoSave` 触发 `PUT /api/v1/scripts/{id}`
- Ctrl+Z/Y → 委托 Monaco 内置 undo（单 session 内），跨 session undo 走 `editor-store` 的 Patch 栈
- 接收外部高亮：`deltaDecorations` 绿色竖条标记

**非受控模式关键逻辑**:
```typescript
// useScriptEditor.ts
const monacoRef = useRef<editor.IStandaloneCodeEditor>(null);

// 外部写入（AI Patch 应用后）
const applyExternalEdit = (newYaml: string) => {
  const model = monacoRef.current.getModel();
  model.pushEditOperations(
    [],
    [{ range: model.getFullModelRange(), text: newYaml }],
    null
  );
};

// 外部高亮
const highlightLines = (lineNumbers: number[]) => {
  const decorations = lineNumbers.map(ln => ({
    range: new Range(ln, 1, ln, 1),
    options: { isWholeLine: true, className: 'source-trace-highlight' }
  }));
  monacoRef.current.deltaDecorations(prevDecorationIds, decorations);
};
```

### 5.3 RightPanel — Tab 切换容器

**Props / Inputs**: `activeTab` (from ui-store)

3 个 Tab，Ant Design Tabs 组件，切换时保留各 Tab 内部状态（CSS `display:none` 而非条件渲染）。

---

#### Tab 1: ScriptPreview（剧本预览）

- 非可编辑渲染视图 — 读取 `script-store.scenes[]`
- 排版规则：
  - Scene Heading 加粗居中
  - Action 两端对齐
  - Dialogue 缩进居中（角色名大写、括号提示、对白内容）
- 点击任意 Element → 前向溯源（通知 `useTraceLinking`）
- 接收外部高亮 → 渲染紫色边框
- 导出按钮：委托 `GET /api/v1/scripts/{id}/export?format=fountain` 文件下载

#### Tab 2: KnowledgeGraph（知识图谱）

- ReactFlow 渲染力导向图
- 节点类型映射：character（圆形/头像色块）、location（方形）、item（菱形）
- 边标签显示关系类型（中文）
- 点击角色节点 → 预览区高亮该角色所有出场 Scene + 主角对话
- 图谱数据来源：`GET /api/v1/tasks/{id}` → `characters_json` + `script_json.knowledge_graph`

#### Tab 3: AIChat（AI 对话）

- 消息列表（Ant Design List/Bubble）+ 底部输入框
- 上下文自动携带：当前选中 Element/Scene 的 `scene_id` + `element_id`
- 发送请求 → `POST /api/v1/editor/chat/{task_id}`（当前非流式，SSE 预留）
- AI 回复中若携带 Patch → 展示 "应用更改" 按钮
- "应用" → `POST /api/v1/editor/apply_patch/{task_id}` → 成功后 → `useScriptEditor.applyExternalEdit()` + `editor-store.pushUndo()`
- 撤销按钮 → `POST /api/v1/editor/undo/{task_id}` → `useScriptEditor.applyExternalEdit()`

### 5.4 TaskBar（顶栏）

- Logo + 项目名（左）
- 任务状态指示灯（绿/黄/红 圆形 + status 文字）— 读取 `task-store.status`
- 导出下拉按钮（YAML / JSON / Fountain）— 调用 `/api/v1/scripts/{id}/export?format=...`
- 用户头像（Ant Avatar）— P1，先写死占位

### 5.5 StatusBar（底栏）

- 左侧：进度条（Ant Progress），读取 `task-store.progress`，animated
- 右侧：SSE 日志滚动窗（最近 5 条），自动换行，超出后 FIFO
- 断点续传按钮：`POST /api/v1/tasks/{task_id}/resume`（仅 failed 状态时可用）

---

## 6. 路由与数据加载时序

### 6.1 数据关系

```
Novel (1) ──────< Task (N) ──────< Script (N)
                                    ↑
                               script_id = task_id
                              （scripts 路由透明映射到 Task 主键）
```

### 6.2 路由表

| 路径 | 页面 | 说明 |
|---|---|---|
| `/` | 剧本列表首页 | 按 novel 分组的剧本卡片 + 上传入口 |
| `/workspace/:taskId` | 主工作台 | 三栏 IDE |
| `/login` | 登录 | P1，先跳过 |

### 6.3 首页 — 剧本列表

```
┌─────────────────────────────────────────────────────┐
│  NovelScript 析幕              [+ 上传新小说]        │
├─────────────────────────────────────────────────────┤
│  搜索/筛选: [按小说名称] [按状态: 全部/进行中/完成]    │
├─────────────────────────────────────────────────────┤
│  ┌─ 《星辰低语》 ─────────────────────────────────┐  │
│  │  ┌──────────┐  ┌──────────┐                   │  │
│  │  │ 写实风格   │  │ 悬疑风格   │                   │  │
│  │  │ S001      │  │ S002      │                   │  │
│  │  │ 12 scenes │  │ 10 scenes │                   │  │
│  │  │ 已完成 ✓   │  │ 转换中 ◐   │                  │  │
│  │  │ 2h ago    │  │ 5m ago    │                   │  │
│  │  └──────────┘  └──────────┘                   │  │
│  │            [+ 新建剧本]                         │  │
│  └────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────┘
```

**交互**：
- 点击卡片 → 进入 `/workspace/:taskId`
- 上传按钮 → 弹出上传 Modal（文本粘贴 or .txt/.md 文件）→ `POST /api/v1/novels/upload` → 获得 novel_id → `POST /api/v1/tasks/ {novel_id}` → 自动跳转 workspace
- 每张卡片显示状态指示灯（绿/黄/红/灰对应 completed/converting/failed/pending）
- 按 novel 分组的折叠列表（Ant Design Collapse），默认展开

### 6.4 Workspace 加载时序

```
页面进入 (/workspace/:taskId)
  │
  ├─ Step 1: 骨架屏 (Ant Skeleton)
  │
  ├─ Step 2: 并行请求
  │    GET /api/v1/tasks/{taskId}
  │    │   → task-store: taskId, novelId, status, progress, errorMessage
  │    │   → 响应含 script_json, script_yaml, characters_json
  │    │
  │    └─ novelId 获得后立即发起:
  │       GET /api/v1/novels/{novel_id}
  │       │   → novel-store: title, chapters[] ({index, title, content})
  │
  ├─ Step 3: 数据就绪
  │    ├─ novel-store.chapters → TipTap 挂载 (约50ms)
  │    ├─ 从 task 响应构建 script-store:
  │    │   yaml = script_yaml, scenes[] = script_json.scenes,
  │    │   characters[] = characters_json,
  │    │   sourceRefMap = 遍历 script_json.scenes[].elements[]
  │    │     → Map<elementId, {chapter_id, offset}>
  │    ├─ Monaco 挂载 yaml 内容 (非受控, 约200ms)
  │    └─ useTraceLinking 激活
  │
  ├─ Step 4: 进度轮询 (if task.status in {preprocessing, converting})
  │    注: 当前 tasks.py 无 SSE 端点 — D3 需补 GET /api/v1/tasks/{task_id}/stream
  │    前端侧预留 useSSE hook，暂用轮询 GET /api/v1/tasks/{task_id}/status
  │    每 2s 更新 task-store.progress
  │
  └─ Step 5: 骨架屏淡出，真实 UI 淡入 (CSS transition opacity 200ms)
```

### 6.5 错误处理

| 场景 | 后端状态码 | 前端处理 |
|---|---|---|
| taskId 不存在 | 404 | ErrorBoundary → "任务不存在" + 返回首页按钮 |
| 剧本尚未生成 (preprocessing) | 200 (script_json=null) | Monaco 显示 "剧本生成中..." placeholder |
| YAML 校验失败 | 422 + detail | editor-store.validationErrors 更新 → Monaco 波浪线 |
| LLM 服务不可用 | 503 | Ant message.error，不阻塞 UI |
| 状态转换非法 | 422 | 静默忽略（前端不应触发非法转换） |
| 轮询断连 | — | 3 次失败后停止，StatusBar 提示 |
| API 超时 (>30s) | — | AbortController → "请求超时，请检查网络" |

---

## 7. 设计令牌（Design Tokens）与视觉基础

### 7.1 色彩系统

```
┌─ Surface ─────────────────────────────────────┐
│  bg-canvas          #0a0a0f   (最深底)         │
│  bg-surface         #14141f   (面板底色)        │
│  bg-elevated        #1c1c2a   (卡片/弹出层)    │
│  bg-hover           #242436   (行悬停)          │
├─ Border ───────────────────────────────────────┤
│  border-subtle      #2a2a3e   (默认分隔)        │
│  border-emphasis    #4a4a6a   (拖拽手柄/焦点)   │
├─ Text ────────────────────────────────────────┤
│  text-primary       #e8e8f0   (正文)            │
│  text-secondary     #9090a8   (辅助/标签)       │
│  text-muted         #585878   (占位/禁用)        │
├─ Accent ───────────────────────────────────────┤
│  accent-primary     #6c5ce7   (主按钮/选中)      │
│  accent-success     #00cec9   (完成/绿灯)        │
│  accent-warning     #fdcb6e   (进行中/黄灯)      │
│  accent-danger      #e17055   (失败/错误/红灯)    │
│  accent-info        #74b9ff   (溯源高亮/蓝)      │
├─ Trace ────────────────────────────────────────┤
│  trace-highlight    rgba(108,92,231,0.35) (溯源联动高亮) │
│  trace-source-bg    rgba(253,203,110,0.35) (原文锚点残留)│
│  trace-marker       #74b9ff   (Monaco 行竖条)   │
└────────────────────────────────────────────────┘
```

深色主题为默认（唯一主题），原因：长时间阅读/编辑的护眼需求 + IDE 范式一致性 + 72h 不做主题切换。

### 7.2 字体

| 用途 | Family | Size | Weight |
|---|---|---|---|
| UI 文本 | Inter, system-ui | 13px | 400 |
| 标题 | Inter | 15px | 600 |
| 原文正文 (TipTap) | Noto Serif SC, serif | 15px | 400 |
| 代码 (Monaco) | JetBrains Mono, monospace | 13px | 400 |
| 剧本预览正文 | Inter | 14px | 400 |

Noto Serif SC 用于原文 — 区分"读小说"和"写代码"两种心智模式。其余全部 Inter。

### 7.3 间距与圆角

```
间距阶梯 (Tailwind 默认):
  xs: 4px  sm: 8px  md: 12px  lg: 16px  xl: 24px

面板内边距: p-lg (16px)
卡片间距: gap-md (12px)
组件内间距: gap-sm (8px)
Splitter 手柄宽: 4px

圆角:
  panel: rounded-none (0)      — 全高面板，无圆角
  card:  rounded-lg (8px)      — 卡片/Modal
  button: rounded-md (6px)     — 按钮/输入框
  tag:    rounded-full (999px) — 标签/徽章
```

### 7.4 图标

使用 `@ant-design/icons` 内置图标集（与 Ant Design 6 一致）：
- 不用独立 icon 库，减小 bundle
- 常用：`UploadOutlined`, `ExportOutlined`, `UndoOutlined`, `RedoOutlined`, `SendOutlined`, `CheckCircleFilled`, `CloseCircleFilled`, `SyncOutlined`

### 7.5 Monaco 配置

```typescript
// Monaco Editor 创建参数
const MONACO_OPTIONS: editor.IStandaloneEditorConstructionOptions = {
  language: 'yaml',
  theme: 'vs-dark',           // 与深色面板统一
  fontSize: 13,
  fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
  lineNumbers: 'on',
  minimap: { enabled: false }, // 72h 不做，D3 可选
  wordWrap: 'on',
  automaticLayout: true,       // 面板 resize 时自动重排
  scrollBeyondLastLine: false,
  renderWhitespace: 'selection',
  tabSize: 2,
  folding: true,               // YAML 折叠
  bracketPairColorization: { enabled: true },
  guides: { indentation: true },
};
```

### 7.6 Tailwind 入口

```css
/* app.css */
@import "tailwindcss";
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600&family=Noto+Serif+SC:wght@400&family=JetBrains+Mono:wght@400&display=swap');

@theme {
  --color-bg-canvas: #0a0a0f;
  --color-bg-surface: #14141f;
  --color-bg-elevated: #1c1c2a;
  --color-accent-primary: #6c5ce7;
  --color-accent-success: #00cec9;
  --color-accent-warning: #fdcb6e;
  --color-accent-danger: #e17055;
  --color-text-primary: #e8e8f0;
  --color-text-secondary: #9090a8;
  --font-serif: 'Noto Serif SC', serif;
  --font-mono: 'JetBrains Mono', monospace;
}
```

---

## 8. API Client 封装

### 8.1 目录结构

```
frontend/app/
├── api/
│   ├── client.ts          # fetch 封装: baseURL, auth header, 错误统一处理
│   ├── novels.ts           # GET/POST novels/*
│   ├── tasks.ts            # GET/POST tasks/*
│   ├── scripts.ts          # GET/PUT/DELETE scripts/*
│   └── editor.ts           # POST editor/*
```

每个 `api/*.ts` 是纯函数，返回带类型的 Promise，不接触 store。

### 8.2 client.ts — 请求基类

```typescript
// api/client.ts
const BASE_URL = '/api/v1';

interface ApiResponse<T> {
  code: number;
  message: string;
  data: T;
}

class ApiError extends Error {
  constructor(
    public status: number,
    public code: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const token = getAuthToken(); // from localStorage or auth store

  const res = await fetch(`${BASE_URL}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  });

  const json: ApiResponse<T> = await res.json();

  if (json.code !== 200 && json.code !== 0) {
    throw new ApiError(res.status, json.code, json.message);
  }

  return json.data;
}
```

### 8.3 各模块签名

```typescript
// api/novels.ts
export function listNovels(page?: number, limit?: number): Promise<{total: number; items: Novel[]}>
export function getNovel(id: string): Promise<{novel: Novel; chapters: Chapter[]}>
export function uploadNovel(content: string, title?: string, author?: string): Promise<UploadResult>
export function uploadNovelFile(file: File, title?: string, author?: string): Promise<UploadResult>
export function deleteNovel(id: string): Promise<{deleted_id: string}>

// api/tasks.ts
export function createTask(novelId: string, pipelineConfig?: object): Promise<{task_id: string; status: string}>
export function getTask(id: string): Promise<TaskFull> // 全量，含 script_yaml/json
export function getTaskStatus(id: string): Promise<TaskStatus> // 轻量，轮询用
export function listTasks(novelId?: string, status?: string, page?: number): Promise<TaskList>
export function resumeTask(id: string): Promise<{task_id: string; status: string}>

// api/scripts.ts
export function listScripts(novelId?: string, status?: string, page?: number): Promise<ScriptList>
export function getScript(id: string): Promise<ScriptFull>
export function updateScript(id: string, scriptYaml: string): Promise<ScriptUpdateResult>
export function deleteScript(id: string): Promise<{script_id: string}>
export function exportScript(id: string, format: 'yaml'|'json'|'fountain'): Promise<string> // raw text

// api/editor.ts
export function sendChat(taskId: string, message: string, sceneId?: string): Promise<ChatResponse>
export function applyPatch(taskId: string, patch: PatchRequest): Promise<{script_json: object; operation_id: string}>
export function undoEdit(taskId: string): Promise<{script_json: object; ...}>
```

### 8.4 错误处理策略

```
ApiError.status === 401 → 清除 token → 跳转 /login (P1；先静默)
ApiError.status === 404 → 组件层捕获 → 对应 UI 提示
ApiError.status === 422 → 解析 detail → Monaco 波浪线 / Ant message.error
ApiError.status >= 500 → Ant message.error("服务暂时不可用") + 不阻塞 UI

网络超时 (AbortController, 30s) → "请求超时，请检查网络"
```

---

## 9. 测试策略

### 9.1 层级与范围

| 层级 | 工具 | 覆盖目标 |
|---|---|---|
| **Store 单测** | Vitest | 5 个 store 的 action 纯逻辑，不依赖 DOM |
| **Hook 单测** | Vitest + `renderHook` | useSSE, useAutoSave, useTraceLinking 核心逻辑 |
| **API mock 集成** | MSW (Mock Service Worker) | 模拟 API 响应，测组件数据加载 + 错误路径 |
| **组件快照** | Vitest + snapshot | 关键组件首渲快照 |
| **E2E 验收** | 手动 | TC-04 双向溯源、TC-05 AI Patch、TC-06 Undo（手动，按 SDS §11） |

### 9.2 关键测试用例

```typescript
// Store 测试
describe('task-store', () => {
  it('setTask sets taskId, novelId, status, progress');
  it('updateProgress merges progress and status');
  it('clearTask resets to initial state');
});

describe('script-store', () => {
  it('loadFromTaskResponse parses scenes from script_json');
  it('buildSourceRefMap creates elementId → {chapter_id, offset} index');
  it('setYaml replaces yaml and marks dirty=false');
});

describe('editor-store', () => {
  it('pushUndo adds patch to stack, clears redoStack');
  it('undo pops from undoStack, pushes to redoStack');
  it('redo pops from redoStack, pushes to undoStack');
  it('undoStack max depth = 50 (cap and warn)');
});

// Hook 测试
describe('useAutoSave', () => {
  it('debounces 2s before calling PUT /api/v1/scripts/{id}');
  it('skips save when dirty=false');
  it('sets validationErrors on 422 response');
});

describe('useTraceLinking', () => {
  it('forward: click element → scrollToOffset called with correct offset');
  it('backward: select source text → finds intersecting elements');
  it('no highlight when sourceRefMap miss');
});

// API Mock 测试
describe('NovelReader loading', () => {
  it('shows Skeleton while chapters loading');
  it('renders TipTap content after chapters loaded');
  it('shows empty placeholder when no novel uploaded');
});
```

### 9.3 72h 内测试优先级

```
D0-D1: 不做前端测试（后端 pytest 覆盖管线）
D2:    Store 单测 + useTraceLinking 单测（核心逻辑最高风险）
D3:    API mock 集成（Chat + Patch + Undo 数据流）
```

---

## 10. 文件清单 & 实施顺序

### 10.1 完整文件清单

```
frontend/app/
├── root.tsx                          # 根布局 (已有，调整)
├── routes.ts                         # 路由配置 (已有，加 /workspace/:taskId)
├── app.css                           # Tailwind v4 + Design Tokens (替换)
├── vite.config.ts                    # Vite 配置 (已有，不需改)
│
├── api/
│   ├── client.ts                     # fetch 封装 + ApiError
│   ├── novels.ts                     # novels CRUD
│   ├── tasks.ts                      # tasks CRUD
│   ├── scripts.ts                    # scripts CRUD
│   └── editor.ts                     # chat / patch / undo
│
├── stores/
│   ├── task-store.ts                 # taskId, novelId, status, progress
│   ├── novel-store.ts                # novelId, title, chapters[], selectedChapterId
│   ├── script-store.ts               # yaml, scenes[], characters[], sourceRefMap
│   ├── editor-store.ts               # undoStack[], redoStack[], dirty, validationErrors[]
│   └── ui-store.ts                   # panelWidths, activeTab
│
├── hooks/
│   ├── useNovelReader.ts             # TipTap ref + scrollTo + highlight
│   ├── useScriptEditor.ts            # Monaco ref + getValue/setValue/applyEdit
│   ├── useTraceLinking.ts            # 双向溯源核心逻辑
│   ├── useSSE.ts                     # SSE 订阅 (P1) + 轮询 fallback (P0)
│   ├── useAutoSave.ts                # 防抖 PUT scripts
│   └── useKeyboard.ts               # Ctrl+S, Ctrl+Z/Y 全局快捷键
│
├── components/
│   ├── task-bar/
│   │   └── TaskBar.tsx               # 顶栏: Logo + 状态灯 + 导出 + 用户头像
│   ├── status-bar/
│   │   └── StatusBar.tsx             # 底栏: 进度条 + 日志滚动
│   ├── splitter/
│   │   └── Splitter.tsx              # 可拖拽三栏分割器
│   ├── novel-reader/
│   │   └── NovelReader.tsx           # TipTap 原文阅读器 (左栏)
│   ├── script-editor/
│   │   └── ScriptEditor.tsx          # Monaco YAML 编辑器 (中栏)
│   ├── right-panel/
│   │   ├── RightPanel.tsx            # Tab 容器
│   │   ├── ScriptPreview.tsx         # Tab1: 剧本预览
│   │   ├── KnowledgeGraph.tsx        # Tab2: ReactFlow 知识图谱
│   │   └── AIChat.tsx               # Tab3: AI 对话面板
│   ├── home/
│   │   └── HomePage.tsx              # 首页: 剧本列表 + 上传入口
│   └── welcome/                      # (已有占位，可删除或重定向)
│
├── routes/
│   ├── home.tsx                      # 首页路由 (重写)
│   └── workspace.tsx                 # /workspace/:taskId (新增)
│
└── __tests__/                        # (D3 补)
    ├── stores/
    │   ├── task-store.test.ts
    │   ├── script-store.test.ts
    │   └── editor-store.test.ts
    ├── hooks/
    │   └── useTraceLinking.test.ts
    └── integration/
        └── workspace-flow.test.ts    # MSW mock
```

### 10.2 实施顺序（对齐 SDS 72h 排期）

```
┌─ D0 (0-8h): 基建 ───────────────────────────────────────────┐
│ 1. app.css             ← Tailwind v4 + Design Tokens        │
│ 2. api/client.ts       ← fetch 封装                         │
│ 3. api/novels.ts       ← novels API 函数                    │
│ 4. api/tasks.ts        ← tasks API 函数                     │
│ 5. api/scripts.ts      ← scripts API 函数                   │
│ 6. api/editor.ts       ← editor API 函数                    │
│ 7. Splitter.tsx        ← 三栏分割器组件                      │
│ 8. routes/workspace.tsx ← 路由骨架 (Skeleton only)           │
│ 9. routes/home.tsx     ← HomePage 路由                       │
│ 10. root.tsx           ← 路由注册调整                        │
└─────────────────────────────────────────────────────────────┘

┌─ D1 (8-20h): Store + Hooks ────────────────────────────────┐
│ 11. task-store.ts                                          │
│ 12. novel-store.ts                                         │
│ 13. script-store.ts    ← 含 sourceRefMap 构建逻辑           │
│ 14. editor-store.ts                                        │
│ 15. ui-store.ts                                            │
│ 16. useAutoSave.ts                                         │
│ 17. useKeyboard.ts                                         │
│ 18. useSSE.ts          ← 轮询 fallback P0, SSE 预留 P1     │
└─────────────────────────────────────────────────────────────┘

┌─ D2 (20-44h): 面板组件 ─────────────────────────────────────┐
│ 19. TaskBar.tsx                                            │
│ 20. StatusBar.tsx                                          │
│ 21. NovelReader.tsx     ← TipTap + useNovelReader           │
│ 22. useNovelReader.ts   ← TipTap ref, scrollTo, highlight  │
│ 23. ScriptEditor.tsx    ← Monaco + useScriptEditor          │
│ 24. useScriptEditor.ts  ← Monaco ref, get/set/apply         │
│ 25. RightPanel.tsx      ← Tab 容器                          │
│ 26. ScriptPreview.tsx   ← Tab1 预览                         │
│ 27. KnowledgeGraph.tsx  ← Tab2 ReactFlow                    │
│ 28. AIChat.tsx          ← Tab3 AI 对话                      │
│ 29. useTraceLinking.ts  ← 双向溯源 (此时三栏都就绪)         │
│ 30. HomePage.tsx        ← 首页完整                           │
└─────────────────────────────────────────────────────────────┘

┌─ D3 (44-60h): 联调打磨 ─────────────────────────────────────┐
│ 31. 全链路数据流联调 (上传→转换→编辑→导出)                   │
│ 32. 异常路径覆盖 (404/422/503 + 空数据兜底)                  │
│ 33. 轮询→SSE 升级 (后端补 stream 端点后)                     │
│ 34. __tests__/ 补核心单测                                    │
│ 35. 导出 Fountain 下载功能                                   │
└─────────────────────────────────────────────────────────────┘
```

### 10.3 组件与 Store / API 依赖速查

| 组件 | 读 Store | 写 Store | 调 API |
|---|---|---|---|
| HomePage | — | — | novels.list, scripts.list, tasks.create, novels.upload |
| TaskBar | task-store | — | scripts.export |
| NovelReader | novel-store | novel-store.selectChapter | — |
| ScriptEditor | script-store, editor-store | editor-store, script-store (on save) | scripts.update |
| ScriptPreview | script-store | — | — |
| KnowledgeGraph | script-store (characters, scenes) | — | — |
| AIChat | task-store (taskId) | editor-store (pushUndo) | editor.chat, editor.applyPatch, editor.undo |
| StatusBar | task-store (progress, error) | — | tasks.resume |
| Splitter | ui-store | ui-store.setPanelWidths | — |

---

## 附录 A. 关键技术决策记录 (ADR)

| ID | 决策 | 理由 | 替代方案 |
|---|---|---|---|
| 1 | 非受控 Monaco | 大 YAML 文件下受控模式每次 keystroke 触发 store 更新导致卡顿 | 受控模式 |
| 2 | Hooks 抽象层 (6 hooks) | DOM 实例（TipTap/Monaco ref）不应放入 store；hooks 做命令式桥接 | 全部放入 store |
| 3 | novel-store 独立 | 原文数据（chapters）不属于 task（任务状态）也不属于 script（剧本产出） | 并入 task-store |
| 4 | 深色主题唯一 | 72h 不做主题切换；深色护眼 + IDE 范式一致 | 亮色 + 系统跟随 |
| 5 | sourceRefMap 在前端构建 | task API 已返回完整 script_json，不需额外溯源 endpoint | 独立溯源 API |
| 6 | 轮询作为 SSE fallback | 当前后端无 SSE 端点 (D3 补)，轮询 GET /status 2s 间隔可接受 | 仅 SSE |
| 7 | Splitter 自研 (~60行CSS) | 无合适 npm 包（alligator 无维护，react-split-pane 卸载），需求极简 | npm 包 |
| 8 | Noto Serif SC 用于原文 | 衬线字体区分"读小说"和"写代码"心智模式 | 统一 Inter |

---

## 附录 B. 与三大UI范式的关系

本篇设计在三栏数据流布局（NovelScript 核心差异化）的基础上，对 PDF 报告中分析的三大范式做了以下吸收：

| 范式 | 吸收点 | 体现位置 |
|---|---|---|
| **专业级创作工具**（单文档中心） | 非受控 Monaco 提供沉浸式编辑；导出 Fountain 保持行业兼容 | §5.2, §5.3 Tab1 |
| **AI 辅助写作**（模块化画布） | RightPanel 三 Tab 按需切换；上下文感知 AI Chat + Patch 应用 | §5.3 Tab3, §4 |
| **AI 转写工具**（目标导向） | 首页一键上传→自动创建 Task→跳转 Workspace 全自动流程 | §6.3 |

PDF 报告中建议的 P1/P2 优化（可折叠面板、焦点模式、大纲编辑器、AI 角色扮演等）不在本 MVP 文档范围，留作后续迭代。
