import { request } from "./client";

export interface ScriptLight {
  script_id: string;
  novel_id: string | null;
  title: string;
  source_type: string;
  status: string;
  progress: number;
  summary: string | null;
  scene_count: number;
  created_at: string | null;
  updated_at: string | null;
}

export interface ScriptFull {
  script_id: string;
  task_id: string | null;
  novel_id: string | null;
  user_id: string | null;
  title: string;
  source_type: string;
  status: string;
  summary: string | null;
  script_yaml: string | null;
  script_json: Record<string, unknown> | null;
  script_fountain: string | null;
  characters_json: Record<string, unknown>[] | null;
  knowledge_graph: {
    nodes: { id: string; node_type: string; name: string; aliases: string[]; description: string | null; properties: Record<string, unknown> }[];
    edges: { id: string; source_node_id: string; target_node_id: string; relation: string; weight: number }[];
  } | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface ScriptUpdateResult {
  script_id: string;
  updated_at: string;
  validation: { valid: boolean; errors: string | null };
}

/** Create a standalone or forked script. */
export function createScript(title: string, sourceType: "standalone" | "forked" = "standalone", novelId?: string, forkFromId?: string) {
  return request<{ script_id: string; title: string; source_type: string }>("/scripts/", {
    method: "POST",
    body: JSON.stringify({ title, source_type: sourceType, novel_id: novelId ?? null, fork_from_id: forkFromId ?? null }),
  });
}

/** Fork an existing script. */
export function forkScript(scriptId: string) {
  return request<{ script_id: string; title: string }>(`/scripts/${scriptId}/fork`, { method: "POST" });
}

export function listScripts(novelId?: string, status?: string, page = 1, limit = 20) {
  const params = new URLSearchParams({ page: String(page), limit: String(limit) });
  if (novelId) params.set("novel_id", novelId);
  if (status) params.set("status", status);
  return request<{ items: ScriptLight[]; total: number; page: number; limit: number }>(
    `/scripts/?${params}`,
  );
}

export function getScript(id: string) {
  return request<ScriptFull>(`/scripts/${id}`);
}

export function updateScript(id: string, scriptYaml: string) {
  return request<ScriptUpdateResult>(`/scripts/${id}`, {
    method: "PUT",
    body: JSON.stringify({ script_yaml: scriptYaml }),
  });
}

export function deleteScript(id: string) {
  return request<{ script_id: string }>(`/scripts/${id}`, { method: "DELETE" });
}

export async function exportScript(
  id: string,
  format: "yaml" | "json" | "fountain",
): Promise<string> {
  // Backend returns raw text (PlainTextResponse), not JSON — bypass request().
  const BASE_URL = import.meta.env.VITE_API_BASE_URL || "/api/v1";
  const res = await fetch(`${BASE_URL}/scripts/${id}/export?format=${format}`);
  if (!res.ok) throw new Error(`导出失败 (${res.status})`);
  return res.text();
}
