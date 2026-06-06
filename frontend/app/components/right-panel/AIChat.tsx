import { useState, useCallback, useRef, useEffect } from "react";
import { Button, Input, message, Select } from "antd";
import { SendOutlined, UndoOutlined } from "@ant-design/icons";
import { useTaskStore } from "../../stores/task-store";
import { useEditorStore } from "../../stores/editor-store";
import { useScriptStore } from "../../stores/script-store";
import { sendChat, applyPatch, undoEdit } from "../../api/editor";
import type { PatchOp, ChatResponse } from "../../api/editor";
import type { useScriptEditor } from "../../hooks/useScriptEditor";

interface MessageItem {
  id: string;
  role: "user" | "assistant";
  content: string;
  patch?: PatchOp | null;
}

interface Props {
  editorHook: ReturnType<typeof useScriptEditor>;
}

let _msgId = 0;
function nextId() {
  return `msg_${++_msgId}`;
}

export function AIChat({ editorHook }: Props) {
  const taskId = useTaskStore((s) => s.taskId);
  const pushUndo = useEditorStore((s) => s.pushUndo);
  const scenes = useScriptStore((s) => s.scenes);
  const [messages, setMessages] = useState<MessageItem[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [sceneId, setSceneId] = useState<string | undefined>(undefined);
  const listRef = useRef<HTMLDivElement>(null);

  // Build scene options from script data
  const sceneOptions = scenes.map((s, i) => {
    const heading = s.heading as Record<string, string> | undefined;
    const sceneIdVal = (s.scene_id as string) || `scene_${i}`;
    const label = heading
      ? `${heading.int_ext || ""} ${heading.location || ""} — ${heading.time || ""}`
      : `场景 ${i + 1}`;
    return { value: sceneIdVal, label: label.trim().replace(/^— /, "") || `场景 ${i + 1}` };
  });

  // Auto-scroll to bottom
  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  const handleSend = useCallback(async () => {
    if (!taskId || !input.trim() || sending) return;
    const userMsg: MessageItem = { id: nextId(), role: "user", content: input };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setSending(true);

    try {
      const res: ChatResponse = await sendChat(taskId, userMsg.content, sceneId);
      setMessages((prev) => [
        ...prev,
        { id: nextId(), role: "assistant", content: res.reply, patch: res.patch },
      ]);
    } catch {
      message.error("AI 服务暂时不可用");
    } finally {
      setSending(false);
    }
  }, [taskId, input, sending]);

  const handleApplyPatch = useCallback(
    async (patch: PatchOp) => {
      if (!taskId) return;
      try {
        const res = await applyPatch(taskId, patch);
        editorHook.applyExternalEdit(JSON.stringify(res.script_json, null, 2));
        pushUndo(patch);
        message.success("更改已应用");
      } catch {
        message.error("应用更改失败");
      }
    },
    [taskId, editorHook, pushUndo],
  );

  const handleUndo = useCallback(async () => {
    if (!taskId) return;
    try {
      const res = await undoEdit(taskId);
      editorHook.applyExternalEdit(JSON.stringify(res.script_json, null, 2));
      message.success("已撤销");
    } catch {
      message.error("撤销失败");
    }
  }, [taskId, editorHook]);

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column" }}>
      {/* Header */}
      <div
        style={{
          padding: "8px 12px",
          borderBottom: "1px solid var(--color-border-subtle)",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          gap: 8,
        }}
      >
        <span style={{ fontWeight: 600, fontSize: 13, flexShrink: 0 }}>AI 助手</span>
        {sceneOptions.length > 0 && (
          <Select
            size="small"
            placeholder="全部场景"
            allowClear
            value={sceneId}
            onChange={(v) => setSceneId(v)}
            options={sceneOptions}
            style={{ flex: 1, minWidth: 0 }}
            maxTagCount={0}
          />
        )}
        <Button size="small" icon={<UndoOutlined />} onClick={handleUndo}>
          撤销
        </Button>
      </div>

      {/* Messages */}
      <div
        ref={listRef}
        style={{
          flex: 1,
          overflow: "auto",
          padding: 12,
          display: "flex",
          flexDirection: "column",
          gap: 8,
        }}
      >
        {messages.length === 0 && (
          <div
            style={{
              textAlign: "center",
              color: "var(--color-text-muted)",
              marginTop: 40,
            }}
          >
            输入消息与 AI 协作编辑剧本
          </div>
        )}
        {messages.map((msg) => (
          <div
            key={msg.id}
            style={{
              padding: "8px 12px",
              borderRadius: 8,
              backgroundColor:
                msg.role === "user" ? "var(--color-bg-elevated)" : "var(--color-bg-canvas)",
              border: "1px solid var(--color-border-subtle)",
              fontSize: 13,
              lineHeight: 1.6,
            }}
          >
            <div style={{ whiteSpace: "pre-wrap" }}>{msg.content}</div>
            {msg.patch && (
              <div style={{ marginTop: 8 }}>
                <Button
                  size="small"
                  type="primary"
                  onClick={() => handleApplyPatch(msg.patch!)}
                >
                  应用更改
                </Button>
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Input */}
      <div
        style={{
          padding: "8px 12px",
          borderTop: "1px solid var(--color-border-subtle)",
          display: "flex",
          gap: 8,
        }}
      >
        <Input.TextArea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onPressEnter={(e) => {
            if (!e.shiftKey) {
              e.preventDefault();
              handleSend();
            }
          }}
          placeholder="输入编辑指令..."
          rows={2}
          style={{ resize: "none" }}
        />
        <Button
          type="primary"
          icon={<SendOutlined />}
          onClick={handleSend}
          loading={sending}
          style={{ alignSelf: "flex-end" }}
        />
      </div>
    </div>
  );
}
