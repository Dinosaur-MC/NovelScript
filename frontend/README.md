# NovelScript Frontend

NovelScript (析幕) 前端工作台 — AI 驱动的长篇小说到结构化剧本转换系统。

## 技术栈

| 类别 | 选型 |
|------|------|
| 框架 | React 19 + TypeScript |
| 构建 | Vite 8 + React Router v7 (SSR) |
| UI 组件 | Ant Design 5 + @ant-design/icons |
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
├── app/                    # React Router 应用入口
│   ├── root.tsx            # 根布局 (HTML 骨架、ErrorBoundary)
│   ├── routes.ts           # 路由配置
│   ├── routes/             # 页面路由组件
│   └── app.css             # 全局样式 (Tailwind)
├── public/                 # 静态资源
├── vite.config.ts          # Vite 配置
├── react-router.config.ts  # React Router 配置
├── tsconfig.json           # TypeScript 配置
├── Dockerfile              # 多阶段 Docker 构建
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
