import { useState, useCallback, useRef, useEffect, useMemo } from "react";
import { Button, Input, message, Select } from "antd";
import { SendOutlined, UndoOutlined } from "@ant-design/icons";
import ReactMarkdown, { type Components } from "react-markdown";
import { useTaskStore } from "../../stores/task-store";
import { useEditorStore } from "../../stores/editor-store";
import { useScriptStore } from "../../stores/script-store";
import { sendChat, applyPatch, undoEdit } from "../../api/editor";
import type { PatchOp, ChatResponse } from "../../api/editor";
import type { useScriptEditor } from "../../hooks/useScriptEditor";

interface MessageItem {
  id: string;
  role: "user" | "assistant";
  /** Full content once streaming is complete. */
  content: string;
  /** Visible content — grows as the typing animation streams in. */
  visibleContent: string;
  patch?: PatchOp | null;
  /** AI reasoning/thinking content (DeepSeek-style). */
  thinking?: string | null;
  /** Whether the thinking section is expanded by the user. */
  thinkingOpen: boolean;
  streaming: boolean;
}

interface Props {
  editorHook: ReturnType<typeof useScriptEditor>;
}

let _msgId = 0;
function nextId() {
  return `msg_${++_msgId}`;
}

/** Typing speed: characters to reveal per animation frame (~60fps). */
const CHARS_PER_TICK = 3;

/**
 * Start a typing animation that progressively reveals text in a message.
 * Returns a cleanup function that can be called to stop the animation early.
 */
function startTypingAnimation(
  msgId: string,
  fullText: string,
  setMessages: React.Dispatch<React.SetStateAction<MessageItem[]>>,
  onDone?: () => void,
): () => void {
  let pos = 0;
  const total = fullText.length;
  let cancelled = false;

  function tick() {
    if (cancelled) return;
    pos = Math.min(pos + CHARS_PER_TICK, total);

    setMessages((prev) =>
      prev.map((m) =>
        m.id === msgId ? { ...m, visibleContent: fullText.slice(0, pos) } : m,
      ),
    );

    if (pos < total) {
      requestAnimationFrame(tick);
    } else {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === msgId ? { ...m, streaming: false } : m,
        ),
      );
      onDone?.();
    }
  }

  requestAnimationFrame(tick);
  return () => { cancelled = true; };
}

export function AIChat({ editorHook }: Props) {
  const scriptId = useScriptStore((s) => s.scriptId);
  const pushUndo = useEditorStore((s) => s.pushUndo);
  const scenes = useScriptStore((s) => s.scenes);
  const scriptTitle = useScriptStore((s) => s.title);
  const [messages, setMessages] = useState<MessageItem[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [sceneId, setSceneId] = useState<string | undefined>(undefined);
  const listRef = useRef<HTMLDivElement>(null);

  // Build scene options from script data
  const sceneOptions = scenes.map((s, i) => {
    const heading = s.heading as Record<string, string> | undefined;
    const sceneIdVal = (s.scene_id as string) || `scene_${i}`;
    const intExt = heading?.int_ext || "";
    const location = heading?.location || "";
    const timeOfDay = heading?.time_of_day || "";
    const parts = [intExt, location, timeOfDay].filter(Boolean);
    const label = parts.join(" ") || `场景 ${i + 1}`;
    return { value: sceneIdVal, label };
  });

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  const handleSend = useCallback(async () => {
    if (!scriptId || !input.trim() || sending) return;
    const userMsg: MessageItem = {
      id: nextId(),
      role: "user",
      content: input,
      visibleContent: input,
      streaming: false,
      thinkingOpen: false,
    };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setSending(true);

    try {
      const res: ChatResponse = await sendChat(scriptId, userMsg.content, sceneId);

      const assistantId = nextId();
      const assistantMsg: MessageItem = {
        id: assistantId,
        role: "assistant",
        content: res.reply,
        visibleContent: "",
        patch: res.patch,
        thinking: res.thinking,
        thinkingOpen: !!res.thinking,
        streaming: true,
      };
      setMessages((prev) => [...prev, assistantMsg]);

      // Start typing animation to stream the response into view
      startTypingAnimation(assistantId, res.reply, setMessages, () => {
        setSending(false);
      });
    } catch {
      message.error("AI 服务暂时不可用");
      setSending(false);
    }
  }, [scriptId, input, sending, sceneId]);

  const handleApplyPatch = useCallback(
    async (patch: PatchOp) => {
      if (!scriptId) return;
      try {
        const res = await applyPatch(scriptId, patch);
        editorHook.applyExternalEdit(JSON.stringify(res.script_json, null, 2));
        pushUndo(patch);
        message.success("更改已应用");
      } catch {
        message.error("应用更改失败");
      }
    },
    [scriptId, editorHook, pushUndo],
  );

  const handleUndo = useCallback(async () => {
    if (!scriptId) return;
    try {
      const res = await undoEdit(scriptId);
      editorHook.applyExternalEdit(JSON.stringify(res.script_json, null, 2));
      message.success("已撤销");
    } catch {
      message.error("撤销失败");
    }
  }, [scriptId, editorHook]);

  /** Custom rendering components for react-markdown — styles code fences. */
  const markdownComponents: Components = useMemo(
    () => ({
      code({ className, children, ...props }: any) {
        const isBlock = className && String(className).includes("language-");
        if (isBlock) {
          return (
            <pre className="ns-chat-code-block">
              <code className={className} {...props}>
                {String(children ?? "")}
              </code>
            </pre>
          );
        }
        return (
          <code className="ns-chat-code-inline" {...props}>
            {String(children ?? "")}
          </code>
        );
      },
    }),
    [],
  );

  return (
    <div className="ns-chat">
      {/* Header */}
      <div className="ns-chat-header">
        <span className="ns-chat-header-title">AI 助手</span>
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
      <div ref={listRef} className="ns-chat-messages">
        {messages.length === 0 && (
          <div className="ns-chat-empty">
            输入消息与 AI 协作编辑剧本
          </div>
        )}
        {messages.map((msg) => {
          const toggleThinking = () => {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === msg.id ? { ...m, thinkingOpen: !m.thinkingOpen } : m,
              ),
            );
          };

          return (
          <div
            key={msg.id}
            className={`ns-chat-msg ${msg.role === "user" ? "ns-chat-msg-user" : "ns-chat-msg-assistant"}`}
          >
            {/* Thinking / reasoning section */}
            {msg.role === "assistant" && msg.thinking && (
              <div className="ns-chat-thinking">
                <button
                  className="ns-chat-thinking-toggle"
                  onClick={toggleThinking}
                >
                  {msg.thinkingOpen ? "▾" : "▸"} 思考过程
                </button>
                {msg.thinkingOpen && (
                  <pre className="ns-chat-thinking-content">{msg.thinking}</pre>
                )}
              </div>
            )}

            <div className="ns-chat-msg-text">
              {msg.role === "assistant" && msg.streaming ? (
                <>
                  <span style={{ whiteSpace: "pre-wrap" }}>{msg.visibleContent}</span>
                  <span className="ns-chat-cursor" />
                </>
              ) : msg.role === "assistant" ? (
                <ReactMarkdown components={markdownComponents}>
                  {msg.content}
                </ReactMarkdown>
              ) : (
                msg.content
              )}
            </div>
            {msg.patch && !msg.streaming && (
              <div className="ns-chat-msg-patch">
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
          );
        })}
      </div>

      {/* Input */}
      <div className="ns-chat-input">
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
