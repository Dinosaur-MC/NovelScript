import { request } from "./client";

export interface Novel {
  id: string;
  title: string;
  author: string | null;
  word_count: number | null;
  language: string;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface Chapter {
  id: string;
  novel_id: string;
  chapter_index: number;
  title: string | null;
  content: string;
  metadata: Record<string, unknown> | null;
  created_at: string;
}

export interface UploadResult {
  novel_id: string;
  title: string;
  chapters: { index: number; title: string }[];
}

export function listNovels(page = 1, limit = 20) {
  return request<{ total: number; items: Novel[] }>(
    `/novels/?page=${page}&limit=${limit}`,
  );
}

export function getNovel(id: string) {
  return request<{ novel: Novel; chapters: Chapter[] }>(`/novels/${id}`);
}

export function uploadNovel(content: string, title?: string, author?: string) {
  return request<UploadResult>("/novels/upload", {
    method: "POST",
    body: JSON.stringify({ content, title, author }),
  });
}

export function uploadNovelFile(file: File, title?: string, author?: string) {
  const form = new FormData();
  form.append("file", file);
  form.append("title", title || "Untitled");
  if (author) form.append("author", author);
  return request<UploadResult>("/novels/upload/file", {
    method: "POST",
    body: form,
    headers: {}, // let browser set multipart boundary
  });
}

export interface NovelKG {
  nodes: { id: string; node_type: string; name: string; aliases: string[]; description: string | null; properties: Record<string, unknown> }[];
  edges: { id: string; source_node_id: string; target_node_id: string; relation: string; weight: number }[];
}

export function getNovelKnowledgeGraph(novelId: string) {
  return request<NovelKG>(`/novels/${novelId}/knowledge-graph`);
}

export function deleteNovel(id: string) {
  return request<{ deleted_id: string }>(`/novels/${id}`, { method: "DELETE" });
}

export function updateNovel(id: string, data: { title?: string; author?: string }) {
  return request<{ novel: Novel }>(`/novels/${id}`, {
    method: "PUT",
    body: JSON.stringify(data),
  });
}
