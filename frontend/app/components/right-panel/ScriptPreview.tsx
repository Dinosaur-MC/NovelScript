import { useCallback } from "react";
import { useScriptStore } from "../../stores/script-store";
import type { useTraceLinking } from "../../hooks/useTraceLinking";

interface Props {
  traceHook: ReturnType<typeof useTraceLinking>;
}

/** Layout constants for screenplay-standard formatting. */
const PAGE_STYLE: React.CSSProperties = {
  maxWidth: 520,
  margin: "0 auto",
  padding: "24px 40px",
  fontFamily: "'Courier New', Consolas, 'Noto Sans SC', monospace",
  fontSize: 13,
  lineHeight: 1.65,
  color: "#d0d0dc",
  backgroundColor: "#12121a",
  borderRadius: 8,
  border: "1px solid var(--color-border-subtle)",
  minHeight: "100%",
};

const SCENE_HEADING: React.CSSProperties = {
  fontWeight: 700,
  textTransform: "uppercase",
  letterSpacing: 1.2,
  fontSize: 13,
  marginBottom: 20,
  color: "var(--color-accent-primary)",
};

const ACTION: React.CSSProperties = {
  marginBottom: 12,
  cursor: "pointer",
  padding: "2px 4px",
  borderRadius: 4,
  transition: "background-color 0.15s",
};

const CHARACTER_NAME: React.CSSProperties = {
  textAlign: "center",
  fontWeight: 700,
  textTransform: "uppercase",
  fontSize: 13,
  letterSpacing: 0.8,
  width: 300,
  margin: "0 auto",
  color: "#c8c8d8",
  paddingTop: 8,
};

const DIALOGUE: React.CSSProperties = {
  textAlign: "left",
  width: 280,
  margin: "0 auto",
  fontSize: 13,
  lineHeight: 1.6,
};

const PARENTHETICAL: React.CSSProperties = {
  textAlign: "center",
  fontSize: 12,
  fontStyle: "italic",
  width: 240,
  margin: "0 auto",
  color: "var(--color-text-secondary)",
};

const TRANSITION: React.CSSProperties = {
  textAlign: "right",
  fontWeight: 600,
  textTransform: "uppercase",
  fontSize: 12,
  letterSpacing: 0.6,
  marginBottom: 20,
  color: "var(--color-text-secondary)",
};

const SCENE_DIVIDER: React.CSSProperties = {
  border: "none",
  borderTop: "1px dashed var(--color-border-subtle)",
  margin: "16px 0 24px",
};

export function ScriptPreview({ traceHook }: Props) {
  const scenes = useScriptStore((s) => s.scenes);

  const handleElementClick = useCallback(
    (elementId: string, sceneId: string, elementIdx: number) => {
      traceHook.onElementClick(elementId, sceneId, elementIdx);
    },
    [traceHook],
  );

  if (scenes.length === 0) {
    return (
      <div
        style={{
          height: "100%",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          color: "var(--color-text-muted)",
          gap: 8,
        }}
      >
        <span style={{ fontSize: 36 }}>🎬</span>
        <span style={{ fontSize: 13 }}>暂无剧本数据</span>
        <span style={{ fontSize: 11 }}>编辑左侧 YAML 后可在此预览</span>
      </div>
    );
  }

  return (
    <div style={{ height: "100%", overflow: "auto", backgroundColor: "var(--color-bg-canvas)" }}>
      <div style={PAGE_STYLE}>
        {scenes.map((scene: Record<string, unknown>, si: number) => {
          const headingRaw = scene.heading;
          const headingStr =
            typeof headingRaw === "string"
              ? headingRaw
              : (headingRaw as Record<string, string>)?.location
                ? `${((headingRaw as Record<string, string>).int_ext ?? "INT.").toUpperCase()}. ${(headingRaw as Record<string, string>).location} — ${(headingRaw as Record<string, string>).time_of_day ?? ""}`
                : `Scene ${si + 1}`;
          const elements = scene.elements as Array<Record<string, unknown>> | undefined;

          return (
            <div key={`${String(scene.scene_id ?? "")}_${si}`}>
              {si > 0 && <hr style={SCENE_DIVIDER} />}

              {/* Scene Heading */}
              <div style={SCENE_HEADING}>{headingStr || `SCENE ${si + 1}`}</div>

              {/* Elements */}
              {elements?.map((el, ei) => {
                const text = (el.content as string) || (el.text as string) || "";
                const charName = (el.character_name as string) || "";
                const dialogue = (el.dialogue as string) || "";
                const parenthetical = el.parenthetical as string | undefined;
                const type = (el.type as string) || "";
                const elId = (el.id as string) || `${scene.scene_id}_${ei}`;

                switch (type) {
                  case "action":
                    return (
                      <p
                        key={ei}
                        onClick={() =>
                          handleElementClick(elId, String(scene.scene_id ?? si), ei)
                        }
                        style={ACTION}
                        onMouseEnter={(e) => {
                          (e.target as HTMLElement).style.backgroundColor =
                            "var(--color-bg-hover)";
                        }}
                        onMouseLeave={(e) => {
                          (e.target as HTMLElement).style.backgroundColor = "transparent";
                        }}
                      >
                        {text}
                      </p>
                    );

                  case "character":
                    return (
                      <div key={ei} style={{ marginBottom: 2 }}>
                        <div style={CHARACTER_NAME}>{text}</div>
                      </div>
                    );

                  case "dialogue":
                  case "dialogue_block":
                    return (
                      <div
                        key={ei}
                        onClick={() =>
                          handleElementClick(elId, String(scene.scene_id ?? si), ei)
                        }
                        style={{ cursor: "pointer", borderRadius: 4, padding: 2, transition: "background-color 0.15s" }}
                        onMouseEnter={(e) => {
                          (e.target as HTMLElement).style.backgroundColor =
                            "var(--color-bg-hover)";
                        }}
                        onMouseLeave={(e) => {
                          (e.target as HTMLElement).style.backgroundColor = "transparent";
                        }}
                      >
                        {charName && <div style={CHARACTER_NAME}>{charName}</div>}
                        {parenthetical && (
                          <div style={PARENTHETICAL}>{parenthetical}</div>
                        )}
                        <div style={DIALOGUE}>{dialogue || text}</div>
                      </div>
                    );

                  case "transition":
                    return (
                      <p key={ei} style={TRANSITION}>
                        {text}
                      </p>
                    );

                  default:
                    return null;
                }
              })}
            </div>
          );
        })}
      </div>
    </div>
  );
}
