import { useRef, useCallback } from "react";
import { message } from "antd";
import { useTaskStore } from "../stores/task-store";
import { useEditorStore } from "../stores/editor-store";
import { updateScript } from "../api/scripts";
import { ApiError } from "../api/types";

const DEBOUNCE_MS = 8_000; // 8s — gives user time to think before save fires

/**
 * Debounced auto-save hook. After calling `triggerSave(yaml)`, the hook waits
 * 8 seconds of inactivity, then fires PUT /api/v1/scripts/{taskId}.
 * Skips the API call if the value hasn't changed since the last successful save.
 * On 422, populates editor-store.validationErrors.
 */
export function useAutoSave() {
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastSavedRef = useRef<string | null>(null);
  const taskId = useTaskStore((s) => s.taskId);
  const setValidationErrors = useEditorStore((s) => s.setValidationErrors);
  const markDirty = useEditorStore((s) => s.markDirty);

  const triggerSave = useCallback(
    (yaml: string) => {
      if (!taskId) return;
      if (timerRef.current) clearTimeout(timerRef.current);

      // Mark dirty only if value differs from last saved
      markDirty(yaml !== lastSavedRef.current);

      timerRef.current = setTimeout(async () => {
        // Skip if nothing changed
        if (yaml === lastSavedRef.current) return;

        try {
          const result = await updateScript(taskId, yaml);
          if (!result.validation.valid) {
            setValidationErrors(
              result.validation.errors ? [result.validation.errors] : ["YAML 校验失败"],
            );
          } else {
            setValidationErrors([]);
            lastSavedRef.current = yaml;
            markDirty(false);
            message.success("已保存");
          }
        } catch (err) {
          console.error("Auto-save failed:", err);
          const msg = err instanceof ApiError && err.status === 401
            ? "登录已过期，请重新登录"
            : "自动保存失败，请检查网络后手动保存";
          message.warning(msg);
        }
      }, DEBOUNCE_MS);
    },
    [taskId, setValidationErrors, markDirty],
  );

  /** Immediate save — no debounce, used by the manual save button. */
  const saveNow = useCallback(
    async (yaml: string) => {
      if (!taskId) return;
      if (timerRef.current) { clearTimeout(timerRef.current); timerRef.current = null; }
      if (yaml === lastSavedRef.current) return;

      try {
        const result = await updateScript(taskId, yaml);
        if (!result.validation.valid) {
          setValidationErrors(
            result.validation.errors ? [result.validation.errors] : ["YAML 校验失败"],
          );
        } else {
          setValidationErrors([]);
          lastSavedRef.current = yaml;
          markDirty(false);
          message.success("已保存");
        }
      } catch (err) {
        console.error("Save failed:", err);
        const msg = err instanceof ApiError && err.status === 401
          ? "登录已过期，请重新登录"
          : "保存失败，请检查网络后重试";
        message.warning(msg);
      }
    },
    [taskId, setValidationErrors, markDirty],
  );

  return { triggerSave, saveNow };
}
