import type { Route } from "./+types/landing";
import { Landing } from "../components/landing/Landing";

export function meta({}: Route.MetaArgs) {
  return [
    { title: "NovelScript 析幕 — AI 驱动的剧本转换系统" },
    { name: "description", content: "将中文长篇小说自动转换为符合行业标准的结构化剧本 (Fountain 1.1 / YAML)。7 阶段确定性管道，百万 token 上下文，知识图谱可视化。" },
  ];
}

export default function LandingPage() {
  return <Landing />;
}
