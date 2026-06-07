import { useRef, useCallback, useEffect } from "react";
import { message } from "antd";
import { useScriptStore } from "../stores/script-store";
import { useEditorStore } from "../stores/editor-store";
import { updateScript } from "../api/scripts";
import { ApiError } from "../api/types";

const DEBOUNCE_MS = 8_000; // 8s — gives user time to think before save fires

/**
 * Debounced auto-save hook. After calling `triggerSave(yaml)`, the hook waits
 * 8 seconds of inactivity, then fires PUT /api/v1/scripts/{scriptId}.
 * Skips the API call if the value hasn't changed since the last successful save.
 * On 422, populates editor-store.validationErrors.
 *
 * Auto-cleans pending timers on unmount to prevent stale saves.
 */
export function useAutoSave() {
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastSavedRef = useRef<string | null>(null);
  const unmountedRef = useRef(false);
  const scriptId = useScriptStore((s) => s.scriptId);
  const setValidationErrors = useEditorStore((s) => s.setValidationErrors);
  const markDirty = useEditorStore((s) => s.markDirty);

  // Cleanup pending timer on unmount
  useEffect(() => {
    unmountedRef.current = false;
    return () => {
      unmountedRef.current = true;
      if (timerRef.current) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    };
  }, []);

  const triggerSave = useCallback(
    (yaml: string) => {
      if (!scriptId) return;
      if (timerRef.current) clearTimeout(timerRef.current);

      markDirty(yaml !== lastSavedRef.current);

      timerRef.current = setTimeout(async () => {
        if (unmountedRef.current) return;
        if (yaml === lastSavedRef.current) return;

        try {
          const result = await updateScript(scriptId, yaml);
          if (unmountedRef.current) return;
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
          if (unmountedRef.current) return;
          console.error("Auto-save failed:", err);
          const msg = err instanceof ApiError && err.status === 401
            ? "登录已过期，请重新登录"
            : "自动保存失败，请检查网络后手动保存";
          message.warning(msg);
        }
      }, DEBOUNCE_MS);
    },
    [scriptId, setValidationErrors, markDirty],
  );

  /** Immediate save — no debounce, used by the manual save button. */
  const saveNow = useCallback(
    async (yaml: string) => {
      if (!scriptId) return;
      if (timerRef.current) { clearTimeout(timerRef.current); timerRef.current = null; }
      if (yaml === lastSavedRef.current) return;

      try {
        const result = await updateScript(scriptId, yaml);
        if (unmountedRef.current) return;
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
        if (unmountedRef.current) return;
        console.error("Save failed:", err);
        const msg = err instanceof ApiError && err.status === 401
          ? "登录已过期，请重新登录"
          : "保存失败，请检查网络后重试";
        message.warning(msg);
      }
    },
    [scriptId, setValidationErrors, markDirty],
  );

  return { triggerSave, saveNow };
}
