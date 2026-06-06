import { request } from "./client";

export interface ChatResponse {
  reply: string;
  patch: PatchOp | null;
}

export interface PatchOp {
  op: string;
  path: string;
  value: unknown;
}

export interface ApplyPatchResult {
  script_json: Record<string, unknown>;
  operation_id: string;
}

export interface UndoResult {
  script_json: Record<string, unknown>;
  undone_operation_id: string;
  rollback_operation_id: string;
}

export function sendChat(taskId: string, message: string, sceneId?: string) {
  return request<ChatResponse>(`/editor/chat/${taskId}`, {
    method: "POST",
    body: JSON.stringify({ message, scene_id: sceneId ?? null }),
  });
}

export function applyPatch(taskId: string, patch: PatchOp) {
  return request<ApplyPatchResult>(`/editor/apply_patch/${taskId}`, {
    method: "POST",
    body: JSON.stringify(patch),
  });
}

export function undoEdit(taskId: string) {
  return request<UndoResult>(`/editor/undo/${taskId}`, { method: "POST" });
}
