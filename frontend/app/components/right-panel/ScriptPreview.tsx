import { useCallback } from "react";
import { useScriptStore } from "../../stores/script-store";
import type { useTraceLinking } from "../../hooks/useTraceLinking";

interface Props { traceHook: ReturnType<typeof useTraceLinking>; }

/* Fountain marker — always visible: muted default, red when forced */
const mk = (ch: string, forced?: boolean) => (
  <span style={{
    color: forced ? "var(--color-accent-danger)" : "var(--color-text-muted)",
    fontWeight: forced ? 700 : 400,
    verticalAlign: "baseline",
    marginRight: 4,
  }}>{ch}</span>
);
const mke = (ch: string) => (
  <span style={{
    color: "var(--color-text-muted)",
    verticalAlign: "baseline",
    marginLeft: 4,
  }}>{ch}</span>
);

export function ScriptPreview({ traceHook }: Props) {
  const scenes = useScriptStore((s) => s.scenes);
  const onEl = useCallback(
    (id: string, sid: string, ei: number) => traceHook.onElementClick(id, sid, ei),
    [traceHook],
  );

  if (scenes.length === 0) {
    return (
      <div style={{ height:"100%", display:"flex", flexDirection:"column", alignItems:"center", justifyContent:"center", color:"var(--color-text-muted)", gap:8 }}>
        <span style={{ fontSize:36 }}>🎬</span>
        <span style={{ fontSize:13 }}>暂无剧本数据</span>
        <span style={{ fontSize:11 }}>编辑 YAML 后实时更新预览</span>
      </div>
    );
  }

  return (
    <div style={{ height:"100%", overflow:"auto", backgroundColor:"var(--color-bg-canvas)" }}>
      <style>{".ns-pe:hover{background-color:rgba(108,92,231,.07)!important;transition:background-color .12s;}"}</style>
      <div style={S.PAGE}>
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
              {si > 0 && <hr style={S.DIVIDER} />}
              <div style={S.SCENE_HD}>
                <span style={S.SCENE_L} />
                <span style={{ whiteSpace:"nowrap", flexShrink:0 }}>{hStr}<span style={S.BADGE}>#{si + 1}</span></span>
                <span style={S.SCENE_R} />
              </div>

              {els?.map((el, ei) => {
                const type = (el.type as string) || "";
                const text = (el.content as string) || (el.text as string) || "";
                const elId = (el.id as string) || `${scene.scene_id}_${ei}`;
                const sid  = String(scene.scene_id ?? si);

                /* ----- action ----- */
                if (type === "action") {
                  const forced   = !!el.is_forced;
                  const centered = !!el.is_centered;
                  return (
                    <div key={ei} className="ns-pe" onClick={() => onEl(elId, sid, ei)}
                      style={{ ...S.EL, ...S.B_ACTION, borderLeftColor:forced ? "var(--color-accent-danger)" : centered ? "rgba(253,203,110,.25)" : "rgba(108,92,231,.20)" }}>
                      <div style={{ lineHeight:1.7, textAlign:centered ? "center" : "justify", fontStyle:centered ? "italic" : "normal" }}>
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
                    <div key={ei} style={{ textAlign:"center", paddingTop:10, marginBottom:2 }}>
                      {mk("@", forced)}
                      <span style={{ fontWeight:600, textTransform:"uppercase", fontSize:13, letterSpacing:1.5, color:"var(--color-accent-info)" }}>
                        {text}
                        {ext && <span style={{ fontSize:11, fontWeight:400, textTransform:"none", color:"var(--color-text-muted)", marginLeft:4 }}>({ext})</span>}
                      </span>
                    </div>
                  );
                }

                /* ----- dialogue ----- */
                if (type === "dialogue") {
                  const par  = el.parenthetical as string | undefined;
                  const dual = !!el.is_dual;
                  return (
                    <div key={ei} className="ns-pe" onClick={() => onEl(elId, sid, ei)}
                      style={{ ...S.EL, ...S.B_DIALOGUE }}>
                      {par && <div style={{ textAlign:"center", fontStyle:"italic", fontSize:12, color:"var(--color-text-secondary)", marginBottom:6 }}>({par})</div>}
                      <div style={{ lineHeight:1.55 }}>
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
                    <div key={ei} className="ns-pe" onClick={() => onEl(elId, sid, ei)}
                      style={{ ...S.EL, ...S.B_DIALOGUE, paddingTop:10 }}>
                      <div style={{ textAlign:"center", fontWeight:700, textTransform:"uppercase", fontSize:14, letterSpacing:1, color:"var(--color-accent-info)", marginBottom:2 }}>
                        {mk("@", charF)}
                        {cn}
                        {ce && <span style={{ fontSize:11, fontWeight:400, textTransform:"none", color:"var(--color-text-muted)", marginLeft:4 }}>({ce})</span>}
                      </div>
                      {par && <div style={{ textAlign:"center", fontStyle:"italic", fontSize:12, color:"var(--color-text-secondary)", marginBottom:4 }}>({par})</div>}
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
                    <div key={ei} className="ns-pe" onClick={() => onEl(elId, sid, ei)}
                      style={{ ...S.EL, ...S.B_TRANSITION }}>
                      <div style={{ textAlign:"right", fontWeight:600, textTransform:"uppercase", fontSize:12, letterSpacing:.8, color:"var(--color-text-secondary)" }}>
                        {mk(">", forced)}{text}
                      </div>
                    </div>
                  );
                }

                /* ----- lyric ----- */
                if (type === "lyric") {
                  return (
                    <div key={ei} className="ns-pe" onClick={() => onEl(elId, sid, ei)}
                      style={{ ...S.EL, ...S.B_LYRIC }}>
                      <div style={{ lineHeight:1.65, fontStyle:"italic", color:"var(--color-accent-warning)" }}>
                        {mk("~")}{text}
                      </div>
                    </div>
                  );
                }

                /* ----- boneyard ----- */
                if (type === "boneyard") {
                  return (
                    <div key={ei} style={{ margin:"0 24px 14px", padding:"6px 12px", borderRadius:6, background:"rgba(88,88,120,.08)" }}>
                      <span style={{ fontSize:12, fontStyle:"italic", color:"var(--color-text-muted)" }}>
                        {mk("/*")}{text}{mke("*/")}
                      </span>
                    </div>
                  );
                }

                /* ----- section ----- */
                if (type === "section") {
                  const lvl = Math.min((el.level as number) || 1, 4);
                  return (
                    <div key={ei} style={{ margin:"20px 0 16px", padding:"8px 0", borderBottom:"1px solid var(--color-border-subtle)" }}>
                      <span style={{ fontWeight:700, textTransform:"uppercase", letterSpacing:1, color:"var(--color-accent-info)" }}>
                        {mk("#".repeat(lvl))}{text}
                      </span>
                    </div>
                  );
                }

                /* ----- synopsis ----- */
                if (type === "synopsis") {
                  return (
                    <div key={ei} style={{ margin:"0 32px 14px", padding:4 }}>
                      <span style={{ fontSize:12, color:"var(--color-text-secondary)" }}>
                        {mk("=")}{text}
                      </span>
                    </div>
                  );
                }

                /* ----- page_break ----- */
                if (type === "page_break") {
                  return <div key={ei} style={{ margin:"28px 0", textAlign:"center" }}>{mk("===")}</div>;
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

/* ---- Styles ---- */
const S = {
  PAGE: {
    padding:"28px 32px",
    fontFamily:"'Noto Sans SC', 'PingFang SC', 'Microsoft YaHei', sans-serif",
    fontSize:14, fontWeight:500, color:"#d8d8e0", backgroundColor:"#12121a",
    borderRadius:8, border:"1px solid var(--color-border-subtle)", minHeight:"100%",
  } as React.CSSProperties,

  EL: {
    position:"relative" as const, marginBottom:14, padding:"5px 8px 5px 10px",
    borderRadius:"0 6px 6px 0", cursor:"pointer",
    borderLeft:"3px solid transparent",
    transition:"background-color .12s, border-left-color .12s",
  } as React.CSSProperties,

  B_ACTION:    { borderLeftColor:"rgba(108,92,231,.20)", marginLeft:0,  marginRight:0 } as React.CSSProperties,
  B_DIALOGUE:  { borderLeftColor:"rgba(0,206,201,.20)",  marginLeft:48, marginRight:48, paddingTop:4, paddingBottom:8 } as React.CSSProperties,
  B_LYRIC:     { borderLeftColor:"rgba(253,203,110,.25)",marginLeft:40, marginRight:40 } as React.CSSProperties,
  B_TRANSITION:{ borderLeftColor:"transparent", borderLeft:"none", marginLeft:0, marginRight:0, paddingTop:8, paddingBottom:4 } as React.CSSProperties,

  SCENE_HD: {
    fontWeight:700, textTransform:"uppercase" as const, letterSpacing:1.4,
    fontSize:13, margin:"0 0 24px", color:"var(--color-accent-primary)",
    display:"flex", alignItems:"center", gap:10,
  } as React.CSSProperties,
  SCENE_L: { flex:1, height:1, background:"linear-gradient(to right, var(--color-accent-primary), transparent)", opacity:.30 } as React.CSSProperties,
  SCENE_R: { flex:1, height:1, background:"linear-gradient(to left,  var(--color-accent-primary), transparent)", opacity:.30 } as React.CSSProperties,
  BADGE: {
    display:"inline-block", fontSize:10, fontWeight:400, letterSpacing:0,
    color:"var(--color-text-muted)", background:"var(--color-bg-elevated)",
    padding:"1px 6px", borderRadius:3, marginLeft:4, verticalAlign:"middle", textTransform:"none",
  } as React.CSSProperties,
  DIVIDER: { border:"none", borderTop:"1px dashed var(--color-border-subtle)", margin:"24px 0 28px", opacity:.45 } as React.CSSProperties,
};
