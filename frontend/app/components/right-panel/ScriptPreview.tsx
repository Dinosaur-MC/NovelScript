import { useCallback } from "react";
import { useScriptStore } from "../../stores/script-store";
import type { useTraceLinking } from "../../hooks/useTraceLinking";

interface Props {
  traceHook: ReturnType<typeof useTraceLinking>;
}

export function ScriptPreview({ traceHook }: Props) {
  const scenes = useScriptStore((s) => s.scenes);

  const handleElementClick = useCallback(
    (sceneId: string, elementIdx: number) => {
      traceHook.onElementClick(`${sceneId}_${elementIdx}`, sceneId, elementIdx);
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
        const heading = scene.heading as Record<string, string> | undefined;
        const elements = scene.elements as Array<Record<string, unknown>> | undefined;

        return (
          <div key={String(scene.scene_id ?? si)} style={{ marginBottom: 32 }}>
            {/* Scene Heading */}
            <h3
              style={{
                textAlign: "center",
                fontWeight: 600,
                marginBottom: 16,
                color: "var(--color-text-primary)",
              }}
            >
              {heading?.text ?? heading?.location ?? `Scene ${si + 1}`}
            </h3>

            {/* Elements */}
            {elements?.map((el, ei) => {
              switch (el.type) {
                case "action":
                  return (
                    <p
                      key={ei}
                      onClick={() => handleElementClick(String(scene.scene_id ?? si), ei)}
                      style={{
                        textAlign: "justify",
                        marginBottom: 12,
                        cursor: "pointer",
                        padding: "2px 4px",
                        borderRadius: 4,
                        transition: "background-color 0.2s",
                      }}
                    >
                      {el.text as string}
                    </p>
                  );
                case "dialogue_block":
                  return (
                    <div
                      key={ei}
                      onClick={() => handleElementClick(String(scene.scene_id ?? si), ei)}
                      style={{
                        textAlign: "center",
                        marginBottom: 12,
                        cursor: "pointer",
                        padding: "4px",
                        borderRadius: 4,
                      }}
                    >
                      <div style={{ fontWeight: 600, textTransform: "uppercase", marginBottom: 4 }}>
                        {el.character_name as string}
                        {el.character_extension ? ` ${el.character_extension}` : ""}
                      </div>
                      {el.parenthetical && (
                        <div style={{ color: "var(--color-text-secondary)", marginBottom: 4 }}>
                          {el.parenthetical as string}
                        </div>
                      )}
                      <div>{(el.dialogue as string) ?? ""}</div>
                    </div>
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
                      {el.text as string}
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
