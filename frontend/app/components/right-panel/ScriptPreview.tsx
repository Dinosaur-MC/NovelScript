import { useCallback } from "react";
import { useScriptStore } from "../../stores/script-store";
import type { useTraceLinking } from "../../hooks/useTraceLinking";

interface Props { traceHook: ReturnType<typeof useTraceLinking>; }

/* Fountain marker — always visible: muted default, red when forced */
const mk = (ch: string, forced?: boolean) => (
  <span className={`ns-preview-mk ${forced ? "ns-preview-mk-open--force" : "ns-preview-mk-open"}`}>{ch}</span>
);
const mke = (ch: string) => (
  <span className="ns-preview-mk-close">{ch}</span>
);

/** Extract a short source-ref label like "ch_01" from an element. */
function sourceBadge(el: Record<string, unknown>): string | null {
  const sr = el.source_ref as { chapter_id?: string } | undefined;
  if (!sr?.chapter_id) return null;
  return sr.chapter_id.replace(/^ch_0?/, "#");
}

export function ScriptPreview({ traceHook }: Props) {
  const scenes = useScriptStore((s) => s.scenes);
  const onEl = useCallback(
    (id: string, sid: string, ei: number) => traceHook.onElementClick(id, sid, ei),
    [traceHook],
  );

  /** Renders a small source badge on elements that have a source_ref. */
  function refBadge(el: Record<string, unknown>) {
    const label = sourceBadge(el);
    if (!label) return null;
    return <span className="ns-preview-ref-badge" title="点击跳转到原文">{label}</span>;
  }

  if (scenes.length === 0) {
    return (
      <div className="ns-preview-empty">
        <span className="ns-preview-empty-icon">🎬</span>
        <span className="ns-preview-empty-title">暂无剧本数据</span>
        <span className="ns-preview-empty-desc">编辑 YAML 后实时更新预览</span>
      </div>
    );
  }

  return (
    <div className="ns-preview-wrap">
      <div className="ns-preview-page">
        {scenes.map((scene: Record<string,unknown>, si: number) => {
          const h        = scene.heading;
          const loc      = (h && typeof h === "object") ? (h as Record<string,string>).location : undefined;
          const intExt   = (h && typeof h === "object") ? (h as Record<string,string>).int_ext : undefined;
          const tod      = (h && typeof h === "object") ? (h as Record<string,string>).time_of_day : undefined;
          const hStr     = loc
            ? `${(intExt ?? "INT.").toUpperCase()} ${loc} — ${tod ?? ""}`
            : typeof h === "string" && h ? h : `SCENE ${si + 1}`;
          const els = scene.elements as Array<Record<string,unknown>> | undefined;

          return (
            <div key={`${scene.scene_id ?? ""}_${si}`}>
              {si > 0 && <hr className="ns-preview-divider" />}
              <div className="ns-preview-scene-hd">
                <span className="ns-preview-scene-l" />
                <span style={{ whiteSpace:"nowrap", flexShrink:0 }}>{hStr}<span className="ns-preview-badge">#{si + 1}</span></span>
                <span className="ns-preview-scene-r" />
              </div>

              {els?.map((el, ei) => {
                const type = (el.type as string) || "";
                const text = (el.content as string) || (el.text as string) || "";
                const elId = (el.id as string | undefined) ?? `${scene.scene_id}_${ei}`;
                const sid  = String(scene.scene_id ?? si);

                /* ----- action ----- */
                if (type === "action") {
                  const forced   = !!el.is_forced;
                  const centered = !!el.is_centered;
                  return (
                    <div key={ei} className="ns-preview-el ns-preview-action ns-preview-el-hover" onClick={() => onEl(elId, sid, ei)}
                      style={{ borderLeftColor: forced ? "var(--color-accent-danger)" : centered ? "rgba(253,203,110,.25)" : "rgba(108,92,231,.20)" }}>
                      <div style={{ lineHeight:1.7, textAlign:centered ? "center" : "justify", fontStyle:centered ? "italic" : "normal" }}>
                        {refBadge(el)}
                        {centered ? mk(">", forced) : mk("!", forced)}
                        {text}
                        {centered && mke("<")}
                      </div>
                    </div>
                  );
                }

                /* ----- character ----- */
                if (type === "character") {
                  const forced = !!el.is_character_forced;
                  const ext = el.character_extension as string | undefined;
                  return (
                    <div key={ei} className="ns-preview-character-cue">
                      {mk("@", forced)}
                      <span className="ns-preview-character-name">
                        {text}
                        {ext && <span className="ns-preview-character-ext">({ext})</span>}
                      </span>
                    </div>
                  );
                }

                /* ----- dialogue ----- */
                if (type === "dialogue") {
                  const par  = el.parenthetical as string | undefined;
                  const dual = !!el.is_dual;
                  return (
                    <div key={ei} className="ns-preview-el ns-preview-dialogue ns-preview-el-hover" onClick={() => onEl(elId, sid, ei)}>
                      {par && <div className="ns-preview-parenthetical" style={{ marginBottom: 6 }}>({par})</div>}
                      <div style={{ lineHeight:1.55 }}>
                        {refBadge(el)}
                        {text}
                        {dual && <span style={{ color:"var(--color-accent-warning)", fontWeight:700 }}> ^</span>}
                      </div>
                    </div>
                  );
                }

                /* ----- dialogue_block ----- */
                if (type === "dialogue_block") {
                  const cn    = (el.character_name as string) || "";
                  const ce    = el.character_extension as string | undefined;
                  const par   = el.parenthetical as string | undefined;
                  const dlg   = (el.dialogue as string) || text;
                  const dual  = !!el.is_dual;
                  const charF = !!el.is_character_forced;
                  return (
                    <div key={ei} className="ns-preview-el ns-preview-dialogue ns-preview-el-hover" onClick={() => onEl(elId, sid, ei)}
                      style={{ paddingTop:10 }}>
                      <div className="ns-preview-dlgblock-char">
                        {mk("@", charF)}
                        {cn}
                        {refBadge(el)}
                        {ce && <span className="ns-preview-character-ext">({ce})</span>}
                      </div>
                      {par && <div className="ns-preview-parenthetical" style={{ marginBottom: 4 }}>({par})</div>}
                      <div style={{ lineHeight:1.55 }}>
                        {dlg}
                        {dual && <span style={{ color:"var(--color-accent-warning)", fontWeight:700 }}> ^</span>}
                      </div>
                    </div>
                  );
                }

                /* ----- transition ----- */
                if (type === "transition") {
                  const forced = !!el.is_forced;
                  return (
                    <div key={ei} className="ns-preview-el ns-preview-transition ns-preview-el-hover" onClick={() => onEl(elId, sid, ei)}>
                      {refBadge(el)}
                      <div className="ns-preview-transition-content">
                        {mk(">", forced)}{text}
                      </div>
                    </div>
                  );
                }

                /* ----- lyric ----- */
                if (type === "lyric") {
                  return (
                    <div key={ei} className="ns-preview-el ns-preview-lyric ns-preview-el-hover" onClick={() => onEl(elId, sid, ei)}>
                      {refBadge(el)}
                      <div className="ns-preview-lyric-content">
                        {mk("~")}{text}
                      </div>
                    </div>
                  );
                }

                /* ----- boneyard ----- */
                if (type === "boneyard") {
                  return (
                    <div key={ei} className="ns-preview-boneyard">
                      <span className="ns-preview-boneyard-text">
                        {mk("/*")}{text}{mke("*/")}
                      </span>
                    </div>
                  );
                }

                /* ----- section ----- */
                if (type === "section") {
                  const lvl = Math.min((el.level as number) || 1, 4);
                  return (
                    <div key={ei} className="ns-preview-section">
                      <span className="ns-preview-section-text">
                        {mk("#".repeat(lvl))}{text}
                      </span>
                    </div>
                  );
                }

                /* ----- synopsis ----- */
                if (type === "synopsis") {
                  return (
                    <div key={ei} className="ns-preview-synopsis">
                      <span className="ns-preview-synopsis-text">
                        {mk("=")}{text}
                      </span>
                    </div>
                  );
                }

                /* ----- page_break ----- */
                if (type === "page_break") {
                  return <div key={ei} className="ns-preview-pagebreak">{mk("===")}</div>;
                }

                return null;
              })}
            </div>
          );
        })}
      </div>
    </div>
  );
}
