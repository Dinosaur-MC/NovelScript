import type { Route } from "./+types/home";
import { HomePage } from "../components/home/HomePage";

export function meta({}: Route.MetaArgs) {
  return [
    { title: "NovelScript 析幕 — 剧本列表" },
    { name: "description", content: "AI 驱动的长篇小说到结构化剧本转换系统" },
  ];
}

export default function Home() {
  return <HomePage />;
}
