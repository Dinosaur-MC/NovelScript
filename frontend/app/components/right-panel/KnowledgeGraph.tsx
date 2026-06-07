import { useMemo, useEffect, useCallback } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  Handle,
  Position,
  MarkerType,
  type Node,
  type Edge,
  type NodeProps,
  type NodeChange,
  useNodesState,
  useEdgesState,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useScriptStore } from "../../stores/script-store";
import type { KGNode, KGEdge } from "../../api/tasks";

// ── Handles ─────────────────────────────────────────────────────────
type HandleSide = "top" | "bottom" | "left" | "right";

const HANDLE_SIDES: HandleSide[] = ["top", "bottom", "left", "right"];

const HANDLE_POS: Record<HandleSide, { position: Position; style: React.CSSProperties }> = {
  top:    { position: Position.Top,    style: { top: 0,    left: "50%", transform: "translate(-50%,-50%)" } },
  bottom: { position: Position.Bottom, style: { bottom: 0, left: "50%", transform: "translate(-50%,50%)" } },
  left:   { position: Position.Left,   style: { left: 0,   top: "50%",  transform: "translate(-50%,-50%)" } },
  right:  { position: Position.Right,  style: { right: 0,  top: "50%",  transform: "translate(50%,-50%)" } },
};

// ── Node styles ─────────────────────────────────────────────────────
// Colours mirror the ScriptPreview palette.
const NODE_STYLES: Record<string, React.CSSProperties> = {
  character:    { background: "var(--color-accent-info)",    color: "#0a0a16", borderRadius: 20, padding: "10px 16px", fontSize: 13, fontWeight: 600, minWidth: 60, textAlign: "center", border: "2px solid rgba(10,10,22,0.12)" },
  location:     { background: "var(--color-accent-primary)",  color: "#f0ecff", borderRadius: 8,  padding: "10px 16px", fontSize: 13, fontWeight: 600, minWidth: 70, textAlign: "center", border: "2px solid rgba(240,236,255,0.18)" },
  item:         { background: "var(--color-accent-warning)",  color: "#1a1808", borderRadius: 6,  padding: "8px 14px",  fontSize: 12, fontWeight: 500, minWidth: 50, textAlign: "center", border: "1px solid rgba(26,24,8,0.15)", transform: "rotate(3deg)" },
  organization: { background: "var(--color-accent-success)",  color: "#061a18", borderRadius: 8,  padding: "9px 15px",  fontSize: 12, fontWeight: 600, minWidth: 60, textAlign: "center", border: "2px solid rgba(6,26,24,0.15)" },
  event:        { background: "var(--color-accent-danger)",   color: "#fff5f2", borderRadius: 14, padding: "8px 14px",  fontSize: 12, fontWeight: 600, minWidth: 50, textAlign: "center", border: "2px solid rgba(255,245,242,0.15)" },
  concept:      { background: "#7c6ff7",                     color: "#f0edff", borderRadius: 4,  padding: "8px 14px",  fontSize: 12, fontWeight: 500, minWidth: 50, textAlign: "center", border: "2px solid rgba(240,237,255,0.15)" },
};

// ── Custom node ─────────────────────────────────────────────────────

function KGNodeComponent({ data, selected }: NodeProps) {
  const nodeStyle = (data.style as React.CSSProperties) ?? {};
  return (
    <div style={{ position: "relative" }}>
      {HANDLE_SIDES.map((s) => (
        <Handle
          key={s}
          type="source"
          position={HANDLE_POS[s].position}
          id={s}
          style={{
            ...HANDLE_POS[s].style,
            width: 8, height: 8,
            background: selected ? "var(--color-accent-info)" : "transparent",
            border: selected ? "2px solid var(--color-accent-info)" : "none",
            borderRadius: "50%",
            opacity: selected ? 1 : 0,
            transition: "opacity 0.12s",
          }}
          isConnectable={false}
        />
      ))}
      {HANDLE_SIDES.map((s) => (
        <Handle
          key={`tgt_${s}`}
          type="target"
          position={HANDLE_POS[s].position}
          id={s}
          style={{ ...HANDLE_POS[s].style, width: 8, height: 8, background: "transparent", border: "none", opacity: 0 }}
          isConnectable={false}
        />
      ))}
      <div style={nodeStyle}>{data.label as string}</div>
    </div>
  );
}

const nodeTypes = { kgNode: KGNodeComponent };

// ── Handle selection ────────────────────────────────────────────────

/** Pick the handle side of *from* that faces toward *to*. */
function bestSide(from: { x: number; y: number }, to: { x: number; y: number }): HandleSide {
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  return Math.abs(dx) >= Math.abs(dy)
    ? (dx >= 0 ? "right" : "left")
    : (dy >= 0 ? "bottom" : "top");
}

/**
 * Patch sourceHandle / targetHandle on every edge so they route via the
 * handle that faces the other node.  Called on initial build and again
 * whenever a node is dragged.
 */
function autoRouteEdges(edges: Edge[], nodePositions: Map<string, { x: number; y: number }>) {
  for (const e of edges) {
    const srcPos = nodePositions.get(e.source);
    const tgtPos = nodePositions.get(e.target);
    if (srcPos && tgtPos) {
      e.sourceHandle = bestSide(srcPos, tgtPos);
      e.targetHandle = bestSide(tgtPos, srcPos);
    }
  }
  return edges;
}

// ── Ring layout ─────────────────────────────────────────────────────
type Ring = "inner" | "middle" | "outer";

function ringRadius(ring: Ring): number {
  switch (ring) {
    case "inner": return 200;
    case "middle": return 310;
    case "outer": return 420;
  }
}

const RING_ORDER: Record<string, { ring: Ring; priority: number }> = {
  character:     { ring: "inner",  priority: 0 },
  item:          { ring: "middle", priority: 1 },
  organization:  { ring: "middle", priority: 2 },
  event:         { ring: "outer",  priority: 3 },
  concept:       { ring: "outer",  priority: 4 },
  location:      { ring: "outer",  priority: 5 },
};

function layoutInRings(entries: { id: string; nodeType: string }[]): Map<string, { x: number; y: number }> {
  const byRing = new Map<Ring, string[]>();
  for (const e of entries) {
    const cfg = RING_ORDER[e.nodeType] ?? { ring: "outer", priority: 5 };
    if (!byRing.has(cfg.ring)) byRing.set(cfg.ring, []);
    byRing.get(cfg.ring)!.push(e.id);
  }
  const positions = new Map<string, { x: number; y: number }>();
  for (const [ring, ids] of byRing) {
    const r = ringRadius(ring as Ring);
    const offset = ring === "inner" ? -Math.PI / 2 : (ring === "middle" ? Math.PI / 7 : -Math.PI / 2);
    for (let i = 0; i < ids.length; i++) {
      const angle = (2 * Math.PI * i) / ids.length + offset;
      positions.set(ids[i], { x: Math.cos(angle) * r, y: Math.sin(angle) * r });
    }
  }
  return positions;
}

// ── Orphaned edge ───────────────────────────────────────────────────

export interface OrphanedEdge {
  edgeId: string;
  relation: string;
  missing: string;
  sourceName: string;
  targetName: string;
}

// ── Build ───────────────────────────────────────────────────────────

interface BuildResult {
  nodes: Node[];
  edges: Edge[];
  positions: Map<string, { x: number; y: number }>;
  orphaned: OrphanedEdge[];
}

function buildGraph(
  kgNodes: KGNode[],
  kgEdges: KGEdge[],
  scenes: Record<string, unknown>[],
): BuildResult {
  const flowNodes: Node[] = [];
  const flowEdges: Edge[] = [];
  const orphanedEdges: OrphanedEdge[] = [];
  const nodeIds = new Set<string>();
  const nodePositions = new Map<string, { x: number; y: number }>();

  // ── 1. KG nodes ───────────────────────────────────────────────────
  const positions = layoutInRings(kgNodes.map((n) => ({ id: n.id, nodeType: n.node_type })));

  for (const kn of kgNodes) {
    const pos = positions.get(kn.id) ?? { x: 0, y: 0 };
    flowNodes.push({
      id: kn.id,
      type: "kgNode",
      data: { label: kn.name, style: NODE_STYLES[kn.node_type] ?? NODE_STYLES.location },
      position: pos,
    });
    nodeIds.add(kn.id);
    nodePositions.set(kn.id, pos);
  }

  // ── 2. Scene location nodes ───────────────────────────────────────
  const seenLocations = new Set<string>();
  for (const scene of scenes) {
    const h = scene.heading as Record<string, string> | undefined;
    const loc = h?.location;
    if (loc && !seenLocations.has(loc) && !nodeIds.has(loc)) {
      seenLocations.add(loc);
      const locId = `loc_${loc.replace(/\s+/g, "_")}`;
      const idx = seenLocations.size;
      const angle = (2 * Math.PI * idx) / Math.max(seenLocations.size, 1) - Math.PI / 2 + 0.3;
      const pos = { x: Math.cos(angle) * 440 + 70, y: Math.sin(angle) * 440 };
      flowNodes.push({
        id: locId, type: "kgNode",
        data: { label: loc, style: NODE_STYLES.location },
        position: pos,
      });
      nodeIds.add(locId);
      nodePositions.set(locId, pos);
    }
  }

  // Name lookup
  const idToName = new Map<string, string>();
  for (const kn of kgNodes) idToName.set(kn.id, kn.name);
  for (const n of flowNodes) {
    if (!idToName.has(n.id) && n.data.label) idToName.set(n.id, n.data.label as string);
  }

  function recordOrphan(edgeId: string, srcId: string, tgtId: string, relation: string) {
    const srcOk = nodeIds.has(srcId), tgtOk = nodeIds.has(tgtId);
    orphanedEdges.push({
      edgeId, relation: relation || "(unknown)",
      missing: !srcOk && !tgtOk ? "both" : !srcOk ? "source" : "target",
      sourceName: idToName.get(srcId) ?? srcId.slice(0, 8),
      targetName: idToName.get(tgtId) ?? tgtId.slice(0, 8),
    });
  }

  // ── 3. KG edges ───────────────────────────────────────────────────
  const MAX_WEIGHT = 4;
  const validKGE = kgEdges.filter((e) => {
    const ok = nodeIds.has(e.source_node_id) && nodeIds.has(e.target_node_id);
    if (!ok) recordOrphan(e.id, e.source_node_id, e.target_node_id, e.relation);
    return ok;
  });
  const maxW = Math.max(1, ...validKGE.map((e) => e.weight));

  for (const e of validKGE) {
    const strokeW = 1 + ((e.weight - 1) / Math.max(maxW - 1, 1)) * (MAX_WEIGHT - 1);
    flowEdges.push({
      id: e.id,
      source: e.source_node_id,
      target: e.target_node_id,
      type: "smoothstep",
      selectable: false,
      interactionWidth: 0,
      markerEnd: { type: MarkerType.ArrowClosed, color: "var(--color-border-emphasis)", width: 14, height: 14 },
      style: {
        stroke: "var(--color-border-emphasis)",
        strokeDasharray: "5 4",
        strokeWidth: Math.round(strokeW * 10) / 10,
      },
      label: e.relation,
      labelStyle: { fill: "var(--color-text-muted)", fontSize: 9, fontWeight: 600, pointerEvents: "none" },
      labelBgStyle: { fill: "var(--color-bg-canvas)", fillOpacity: 0.85, pointerEvents: "none" },
    });
  }

  // ── 4. Character‑in‑scene → location edges ────────────────────────
  const sceneLocMap = new Map<number, string>();
  for (let si = 0; si < scenes.length; si++) {
    const h = scenes[si].heading as Record<string, string> | undefined;
    if (h?.location) sceneLocMap.set(si, `loc_${String(h.location).replace(/\s+/g, "_")}`);
  }

  const nameToId = new Map<string, string>();
  for (const kn of kgNodes) {
    nameToId.set(kn.name, kn.id);
    for (const a of kn.aliases) nameToId.set(a, kn.id);
  }

  const edgeSeen = new Set<string>();
  for (let si = 0; si < scenes.length; si++) {
    const targetLocId = sceneLocMap.get(si);
    if (!targetLocId) continue;
    if (!nodeIds.has(targetLocId)) {
      if (!edgeSeen.has(`orphan_loc_${targetLocId}`)) {
        edgeSeen.add(`orphan_loc_${targetLocId}`);
        orphanedEdges.push({
          edgeId: `scene_${si}_loc`, relation: "appears_in", missing: "target",
          sourceName: `Scene ${si + 1}`, targetName: targetLocId,
        });
      }
      continue;
    }

    const elements = scenes[si].elements as Array<Record<string, unknown>> | undefined;
    if (!elements) continue;

    const sceneChars = new Set<string>();
    for (const el of elements) {
      const chName = el.character_name as string | undefined;
      if (!chName) continue;
      const chId = nameToId.get(chName);
      if (chId) sceneChars.add(chId);
      else if (!edgeSeen.has(`orphan_ch_${chName}`)) {
        edgeSeen.add(`orphan_ch_${chName}`);
        orphanedEdges.push({
          edgeId: `scene_${si}_ch`, relation: "appears_as", missing: "source",
          sourceName: chName, targetName: targetLocId,
        });
      }
    }

    for (const chId of sceneChars) {
      const edgeKey = `${chId}->${targetLocId}`;
      if (edgeSeen.has(edgeKey)) continue;
      edgeSeen.add(edgeKey);
      flowEdges.push({
        id: `sc_${si}_${edgeKey}`,
        source: chId,
        target: targetLocId,
        type: "smoothstep",
        selectable: false,
        interactionWidth: 0,
        markerEnd: { type: MarkerType.ArrowClosed, color: "var(--color-text-muted)", width: 12, height: 12 },
        style: { stroke: "var(--color-text-muted)", strokeDasharray: "3 5", strokeWidth: 1 },
        label: `S${si + 1}`,
        labelStyle: { fill: "var(--color-text-muted)", fontSize: 9, fontWeight: 500, pointerEvents: "none" },
        labelBgStyle: { fill: "var(--color-bg-canvas)", fillOpacity: 0.7, pointerEvents: "none" },
      });
    }
  }

  // Compute initial handle routing
  autoRouteEdges(flowEdges, nodePositions);

  return { nodes: flowNodes, edges: flowEdges, positions: nodePositions, orphaned: orphanedEdges };
}

// ── Component ───────────────────────────────────────────────────────

export function KnowledgeGraph() {
  const kg = useScriptStore((s) => s.knowledgeGraph);
  const scenes = useScriptStore((s) => s.scenes);

  const { nodes: initialNodes, edges: initialEdges, positions: initialPositions, orphaned } = useMemo(
    () => {
      if (!kg || kg.nodes.length === 0) {
        return { nodes: [], edges: [], positions: new Map<string, { x: number; y: number }>(), orphaned: [] as OrphanedEdge[] };
      }
      return buildGraph(kg.nodes, kg.edges, scenes);
    },
    [kg, scenes],
  );

  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);

  useEffect(() => setNodes(initialNodes), [initialNodes, setNodes]);
  useEffect(() => setEdges(initialEdges), [initialEdges, setEdges]);

  // Track live node positions so we can re-route edges when nodes move
  const livePositions = useMemo(() => new Map(initialPositions), [initialPositions]);

  /** When nodes change (position drag), update cached positions and
   *  recompute every edge's sourceHandle / targetHandle. */
  const handleNodesChange = useCallback(
    (changes: NodeChange[]) => {
      onNodesChange(changes);

      // Update position cache for moved nodes
      let needReroute = false;
      for (const ch of changes) {
        if (ch.type === "position" && "id" in ch && "position" in ch) {
          livePositions.set(ch.id, ch.position as { x: number; y: number });
          needReroute = true;
        }
      }

      if (needReroute) {
        setEdges((prev) => [...autoRouteEdges([...prev], livePositions)]);
      }
    },
    [onNodesChange, setEdges, livePositions],
  );

  if (initialNodes.length === 0) {
    return <div className="ns-kg-empty">暂无图谱数据</div>;
  }

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column" }}>
      {orphaned.length > 0 && (
        <div className="ns-kg-orphaned">
          <span className="ns-kg-orphaned-title">
            ⚠ {orphaned.length} 条连线缺少节点，未渲染
          </span>
          <ul className="ns-kg-orphaned-list">
            {orphaned.slice(0, 8).map((o) => (
              <li key={o.edgeId} className="ns-kg-orphaned-item">
                {o.missing === "source" && <>缺失源节点 <code>{o.sourceName}</code> → <code>{o.targetName}</code>（{o.relation}）</>}
                {o.missing === "target" && <><code>{o.sourceName}</code> → 缺失目标节点 <code>{o.targetName}</code>（{o.relation}）</>}
                {o.missing === "both" && <>两端缺失: <code>{o.sourceName}</code> ↔ <code>{o.targetName}</code></>}
              </li>
            ))}
            {orphaned.length > 8 && <li className="ns-kg-orphaned-item">... 还有 {orphaned.length - 8} 条</li>}
          </ul>
        </div>
      )}
      <div style={{ flex: 1 }}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={handleNodesChange}
          onEdgesChange={onEdgesChange}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.3, maxZoom: 1.5 }}
          attributionPosition="bottom-left"
          defaultViewport={{ x: 0, y: 0, zoom: 0.6 }}
        >
          <Background color="var(--color-border-subtle)" />
          <Controls />
        </ReactFlow>
      </div>
    </div>
  );
}
