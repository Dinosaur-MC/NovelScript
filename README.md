# NovelScript | 析幕

> AI 驱动的长篇小说到结构化剧本转换系统

## 🎯 项目简介 (Project Overview)

NovelScript (析幕) 是一个面向网文 IP 改编市场的企业级 AI 内容管线系统。它突破了传统大模型在处理长文本时的上下文限制与输出不稳定性，通过**异步并发解析、FAISS 向量知识库构建**以及**双向溯源映射（Trace Mapping）**技术，能够将 3 个章节以上的长篇小说，精准转化为符合影视工业标准（兼容 Final Draft 思想）的结构化 YAML/JSON 剧本。

## ✨ 核心特性 (Core Features)

- 🚀 **异步并发管线**：基于 FastAPI + Celery/Asyncio 构建，支持多章节分块并发调用 LLM，大幅缩短长文本处理时间。
- 🧠 **长文本记忆网络**：结合 FAISS 向量数据库与 Pydantic 模型，构建全局角色表与场景摘要，解决 LLM 的“中间遗忘（Lost in the Middle）”问题。
- 🛡️ **工业级格式兜底**：独创的 YAML Schema 规范，配合 LangChain `PydanticOutputParser` 与**自动重试修复机制**，确保输出格式 100% 合法可用。
- 🔗 **双向溯源系统**：剧本字段自带偏移量锚点，支持在前端编辑器中一键跳转回小说原文，确保 AI 改编的“可审计性”。
