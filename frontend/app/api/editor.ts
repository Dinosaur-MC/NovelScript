import { request } from "./client";

export interface ChatResponse {
  reply: string;
  patch: PatchOp | null;
  thinking: string | null;
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

/** Send a chat message scoped to a Script. */
export function sendChat(scriptId: string, message: string, sceneId?: string) {
  return request<ChatResponse>(`/editor/chat/${scriptId}`, {
    method: "POST",
    body: JSON.stringify({ message, scene_id: sceneId ?? null }),
  });
}

/** Apply a JSON Patch to the Script. */
export function applyPatch(scriptId: string, patch: PatchOp) {
  return request<ApplyPatchResult>(`/editor/apply_patch/${scriptId}`, {
    method: "POST",
    body: JSON.stringify(patch),
  });
}

/** Undo the most recent patch on the Script. */
export function undoEdit(scriptId: string) {
  return request<UndoResult>(`/editor/undo/${scriptId}`, { method: "POST" });
}
