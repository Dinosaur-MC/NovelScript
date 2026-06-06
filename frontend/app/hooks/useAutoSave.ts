import { useRef, useCallback } from "react";
import { message } from "antd";
import { useTaskStore } from "../stores/task-store";
import { useEditorStore } from "../stores/editor-store";
import { updateScript } from "../api/scripts";
import { ApiError } from "../api/types";

/**
 * Debounced auto-save hook. After calling `triggerSave(yaml)`, the hook waits
 * 2 seconds of inactivity, then fires PUT /api/v1/scripts/{taskId}.
 * On 422, populates editor-store.validationErrors.
 */
export function useAutoSave() {
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const taskId = useTaskStore((s) => s.taskId);
  const setValidationErrors = useEditorStore((s) => s.setValidationErrors);

  const triggerSave = useCallback(
    (yaml: string) => {
      if (!taskId) return;
      if (timerRef.current) clearTimeout(timerRef.current);

      timerRef.current = setTimeout(async () => {
        try {
          const result = await updateScript(taskId, yaml);
          if (!result.validation.valid) {
            setValidationErrors(
              result.validation.errors ? [result.validation.errors] : ["YAML 校验失败"],
            );
          } else {
            setValidationErrors([]);
          }
        } catch (err) {
          console.error("Auto-save failed:", err);
          const msg = err instanceof ApiError && err.status === 401
            ? "登录已过期，请重新登录"
            : "自动保存失败，请检查网络后手动保存";
          message.warning(msg);
        }
      }, 2000);
    },
    [taskId, setValidationErrors],
  );

  return { triggerSave };
}
