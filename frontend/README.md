# NovelScript Frontend

NovelScript (析幕) 前端工作台 — AI 驱动的长篇小说到结构化剧本转换系统。

## 技术栈

| 类别 | 选型 |
|------|------|
| 框架 | React 19 + TypeScript |
| 构建 | Vite 8 + React Router v7 (SSR) |
| UI 组件 | Ant Design 6 + @ant-design/icons |
| 富文本 | TipTap 3 |
| 代码编辑 | Monaco Editor (@monaco-editor/react) |
| 知识图谱 | ReactFlow (@xyflow/react) |
| 状态管理 | Zustand 5 |
| 样式 | Tailwind CSS 4 |
| XSS 防护 | DOMPurify |

## 快速开始

```bash
# 安装依赖
pnpm install

# 开发模式 (HMR)
pnpm run dev

# 生产构建
pnpm run build

# 启动生产服务
pnpm run start
```

- 开发服务器: `http://localhost:5173`
- 生产服务器: `http://localhost:3000`

## Docker 部署

```bash
docker build -t novelscript-frontend .
docker run -p 3000:3000 novelscript-frontend
```

## 项目结构

```text
frontend/
├── app/                      # React Router 应用入口 (SSR)
│   ├── root.tsx              # 根布局 (HTML 骨架、ErrorBoundary)
│   ├── routes.ts             # 路由配置
│   ├── routes/               # 页面路由组件
│   │   ├── home.tsx          # 首页
│   │   ├── login.tsx         # 登录页
│   │   ├── dashboard.tsx     # 仪表盘
│   │   └── workspace.tsx     # 主工作台 (三栏布局)
│   ├── components/           # UI 组件
│   │   ├── ClientOnly.tsx
│   │   ├── home/             # HomePage
│   │   ├── novel-reader/     # TipTap 原文阅读器 (左栏)
│   │   ├── script-editor/    # Monaco YAML 编辑器 (中栏)
│   │   ├── right-panel/      # RightPanel, ScriptPreview, KnowledgeGraph, AIChat (右栏)
│   │   ├── task-bar/         # 顶栏: Logo + 任务状态 + 导出
│   │   ├── status-bar/       # 底栏: 进度条 + 日志
│   │   └── splitter/         # 可拖拽面板分割器
│   ├── api/                  # API 客户端层 (axios)
│   │   ├── client.ts         # Axios 实例 + 拦截器
│   │   ├── types.ts          # API 类型定义
│   │   ├── auth.ts           # /auth 端点
│   │   ├── novels.ts         # /novels 端点
│   │   ├── scripts.ts        # /scripts 端点
│   │   ├── tasks.ts          # /tasks 端点 (含 SSE)
│   │   └── editor.ts         # /editor 端点
│   ├── stores/               # Zustand 状态管理
│   │   ├── auth-store.ts     # 用户认证
│   │   ├── novel-store.ts    # 小说/原文
│   │   ├── script-store.ts   # 剧本数据
│   │   ├── editor-store.ts   # 编辑器状态
│   │   ├── task-store.ts     # 任务管线状态
│   │   └── ui-store.ts       # UI 布局状态
│   ├── hooks/                # 自定义 Hooks
│   │   ├── useAutoSave.ts    # 自动保存
│   │   ├── useKeyboard.ts    # 快捷键绑定
│   │   ├── useNovelReader.ts # 原文阅读器
│   │   ├── useSSE.ts         # SSE 进度订阅
│   │   ├── useScriptEditor.ts # Monaco 编辑器
│   │   └── useTraceLinking.ts # 双向溯源联动
│   ├── app.css               # 全局样式 (Tailwind + 暗色主题)
│   ├── entry.server.tsx      # React Router SSR 入口
│   └── ssr-cache.ts          # SSR 响应缓存
├── __tests__/                # Vitest 测试 (9 个)
│   ├── hooks/                # 3 hook 测试
│   └── stores/               # 6 store 测试
├── public/                   # 静态资源
├── vite.config.ts            # Vite 配置
├── react-router.config.ts    # React Router 配置
├── tsconfig.json             # TypeScript 配置
├── Dockerfile                # 多阶段 Docker 构建 (deps → builder → runner)
└── package.json
```

## 三栏工作台布局

```
┌─────────────┬──────────────┬─────────────┐
│  左栏 (30%)  │  中栏 (40%)   │  右栏 (30%)  │
│  TipTap     │  Monaco      │  预览/图谱   │
│  原文阅读器  │  YAML 编辑器  │  AI 对话    │
└─────────────┴──────────────┴─────────────┘
```
