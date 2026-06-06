import { useCallback } from "react";
import { useScriptStore } from "../../stores/script-store";
import type { useTraceLinking } from "../../hooks/useTraceLinking";

interface Props {
  traceHook: ReturnType<typeof useTraceLinking>;
}

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
          alignItems: "center",
          justifyContent: "center",
          color: "var(--color-text-muted)",
        }}
      >
        暂无剧本数据
      </div>
    );
  }

  return (
    <div
      style={{
        height: "100%",
        overflow: "auto",
        padding: "24px 20px",
        fontFamily: "var(--font-sans)",
        fontSize: 14,
        lineHeight: 1.7,
      }}
    >
      {scenes.map((scene: Record<string, unknown>, si: number) => {
        // heading can be a string ("地点 — 时间") or an object ({text, location, time_of_day})
        const headingRaw = scene.heading;
        const headingStr = typeof headingRaw === "string" ? headingRaw : (headingRaw as Record<string, string>)?.text || (headingRaw as Record<string, string>)?.location || `Scene ${si + 1}`;
        const elements = scene.elements as Array<Record<string, unknown>> | undefined;

        return (
          <div key={`${String(scene.scene_id ?? "")}_${si}`} style={{ marginBottom: 32 }}>
            {/* Scene Heading */}
            <h3
              style={{
                textAlign: "center",
                fontWeight: 600,
                marginBottom: 16,
                color: "var(--color-text-primary)",
              }}
            >
              {headingStr || `Scene ${si + 1}`}
            </h3>

            {/* Elements */}
            {elements?.map((el, ei) => {
              // Field names in the YAML: "content" (action/dialogue text), "character_name", "dialogue"
              const text = (el.content as string) || (el.text as string) || "";
              const charName = (el.character_name as string) || "";
              const dialogue = (el.dialogue as string) || "";
              const type = (el.type as string) || "";
              const elId = (el.id as string) || `${scene.scene_id}_${ei}`;

              switch (type) {
                case "action":
                  return (
                    <p
                      key={ei}
                      onClick={() => handleElementClick(elId, String(scene.scene_id ?? si), ei)}
                      style={{
                        textAlign: "justify",
                        marginBottom: 12,
                        cursor: "pointer",
                        padding: "2px 4px",
                        borderRadius: 4,
                        transition: "background-color 0.2s",
                      }}
                    >
                      {text}
                    </p>
                  );
                case "dialogue":
                case "dialogue_block":
                  return (
                    <div
                      key={ei}
                      onClick={() => handleElementClick(elId, String(scene.scene_id ?? si), ei)}
                      style={{
                        textAlign: "center",
                        marginBottom: 12,
                        cursor: "pointer",
                        padding: "4px",
                        borderRadius: 4,
                      }}
                    >
                      {charName && (
                        <div style={{ fontWeight: 600, textTransform: "uppercase", marginBottom: 4 }}>
                          {charName}
                          {el.character_extension ? ` ${el.character_extension}` : ""}
                        </div>
                      )}
                      {(el.parenthetical as string | undefined) && (
                        <div style={{ color: "var(--color-text-secondary)", marginBottom: 4 }}>
                          {el.parenthetical as string}
                        </div>
                      )}
                      <div>{dialogue || text}</div>
                    </div>
                  );
                case "character":
                  return (
                    <p
                      key={ei}
                      style={{
                        textAlign: "center",
                        marginBottom: 12,
                        color: "var(--color-text-secondary)",
                      }}
                    >
                      {text}
                    </p>
                  );
                case "transition":
                  return (
                    <p
                      key={ei}
                      style={{
                        textAlign: "right",
                        fontWeight: 600,
                        marginBottom: 12,
                        color: "var(--color-text-secondary)",
                      }}
                    >
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
  );
}
