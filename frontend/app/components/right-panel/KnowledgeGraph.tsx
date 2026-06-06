import { useMemo, useEffect } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  type Node,
  type Edge,
  useNodesState,
  useEdgesState,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useScriptStore } from "../../stores/script-store";

const NODE_STYLE: Record<string, React.CSSProperties> = {
  character: {
    background: "var(--color-accent-primary)",
    color: "#fff",
    borderRadius: "50%",
    width: 40,
    height: 40,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    fontSize: 12,
    fontWeight: 600,
  },
  location: {
    background: "var(--color-accent-success)",
    color: "#000",
    borderRadius: 6,
    padding: "8px 12px",
    fontSize: 12,
    fontWeight: 600,
  },
  item: {
    background: "var(--color-accent-warning)",
    color: "#000",
    borderRadius: 2,
    padding: "6px 10px",
    fontSize: 12,
    transform: "rotate(45deg)",
  },
};

interface GraphData {
  nodes: Node[];
  edges: Edge[];
}

/**
 * Build graph nodes and edges from character/item/location data and scenes.
 * - Character nodes: circle layout (inner ring)
 * - Item / organization / event / concept nodes: middle ring (diamond shape)
 * - Location nodes: circle layout (outer ring), from scene headings
 * - Edges: character ↔ location when character appears in a scene
 *   Edge stroke width scales with appearance count across scenes.
 * Positions are fully deterministic (index-based) to avoid SSR mismatches.
 */
function buildGraph(
  characters: Record<string, unknown>[],
  scenes: Record<string, unknown>[],
): GraphData {
  const nodes: Node[] = [];
  const edges: Edge[] = [];

  // ── Separate characters from other entity types ───────────────────
  const chars: Record<string, unknown>[] = [];
  const items: Record<string, unknown>[] = [];
  for (const c of characters) {
    const nodeType = c.node_type as string | undefined;
    if (nodeType && nodeType !== "character") {
      items.push(c);
    } else {
      chars.push(c);
    }
  }

  // ── Character nodes (inner ring, radius ~180px) ──────────────────
  for (let i = 0; i < chars.length; i++) {
    const ch = chars[i];
    const chId = (ch.id as string) || `ch_${i}`;
    const angle = (2 * Math.PI * i) / Math.max(chars.length, 1);
    nodes.push({
      id: chId,
      type: "default",
      data: { label: (ch.name as string) || chId },
      position: { x: Math.cos(angle) * 180, y: Math.sin(angle) * 180 },
      style: NODE_STYLE.character,
    });
  }

  // ── Item / org / event / concept nodes (middle ring, radius ~250px)
  for (let i = 0; i < items.length; i++) {
    const it = items[i];
    const itId = (it.id as string) || `item_${i}`;
    const angle = (2 * Math.PI * i) / Math.max(items.length, 1) + Math.PI / 8; // offset from chars
    const nodeType = it.node_type as string;
    const styleKey = (nodeType === "item") ? "item" : "location"; // fallback style
    nodes.push({
      id: itId,
      type: "default",
      data: { label: (it.name as string) || itId },
      position: { x: Math.cos(angle) * 250 + 30, y: Math.sin(angle) * 250 },
      style: { ...NODE_STYLE[styleKey] || NODE_STYLE.location, fontSize: 11 },
    });
  }

  // ── Location nodes (outer ring, radius ~320px) ───────────────────
  const seenLocations = new Set<string>();
  const locs: string[] = [];
  const sceneLocMap = new Map<number, string>();

  for (let si = 0; si < scenes.length; si++) {
    const heading = scenes[si].heading as Record<string, string> | undefined;
    const loc = heading?.location;
    if (loc && !seenLocations.has(loc)) {
      seenLocations.add(loc);
      locs.push(loc);
    }
    if (loc) {
      sceneLocMap.set(si, `loc_${loc}`);
    }
  }

  for (let i = 0; i < locs.length; i++) {
    const angle = (2 * Math.PI * i) / Math.max(locs.length, 1);
    nodes.push({
      id: `loc_${locs[i]}`,
      type: "default",
      data: { label: locs[i] },
      position: { x: Math.cos(angle) * 320 + 50, y: Math.sin(angle) * 320 },
      style: NODE_STYLE.location,
    });
  }

  // ── Edges: character appears in scene → edge to location ─────────
  // Count appearances for edge weighting (stroke width 1–4 px)
  const edgeWeight = new Map<string, { count: number; lastScene: number }>();

  for (let si = 0; si < scenes.length; si++) {
    const scene = scenes[si];
    const targetLocId = sceneLocMap.get(si);
    if (!targetLocId) continue;

    const elements = scene.elements as Array<Record<string, unknown>> | undefined;
    if (!elements) continue;

    for (const el of elements) {
      const chName = el.character_name;
      if (!chName) continue;

      for (const ch of chars) {
        const chId = ch.id as string;
        if (chId === chName || (ch.name as string) === chName) {
          const edgeKey = `${chId}->${targetLocId}`;
          const prev = edgeWeight.get(edgeKey);
          edgeWeight.set(edgeKey, {
            count: (prev?.count ?? 0) + 1,
            lastScene: si + 1,
          });
        }
      }
    }
  }

  const MAX_WEIGHT = 4;
  const MIN_WEIGHT = 1;
  const maxCount = Math.max(1, ...[...edgeWeight.values()].map((v) => v.count));

  for (const [key, val] of edgeWeight) {
    const strokeW = MIN_WEIGHT + ((val.count - 1) / Math.max(maxCount - 1, 1)) * (MAX_WEIGHT - MIN_WEIGHT);
    edges.push({
      id: key,
      source: key.split("->")[0],
      target: key.split("->")[1],
      style: {
        stroke: "var(--color-border-emphasis)",
        strokeDasharray: "4 3",
        strokeWidth: Math.round(strokeW * 10) / 10,
      },
      label: maxCount > 1 ? `S${val.lastScene}` : `Scene ${val.lastScene}`,
      labelStyle: { fill: "var(--color-text-muted)", fontSize: 10 },
      labelBgStyle: { fill: "var(--color-bg-canvas)" },
    });
  }

  return { nodes, edges };
}

export function KnowledgeGraph() {
  const characters = useScriptStore((s) => s.characters);
  const scenes = useScriptStore((s) => s.scenes);

  const { nodes: initialNodes, edges: initialEdges } = useMemo(
    () => buildGraph(characters, scenes),
    [characters, scenes],
  );

  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);

  // Sync when async data arrives after mount (useNodesState/useEdgesState
  // only consume initial values, like useState)
  useEffect(() => setNodes(initialNodes), [initialNodes, setNodes]);
  useEffect(() => setEdges(initialEdges), [initialEdges, setEdges]);

  if (initialNodes.length === 0) {
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
        暂无图谱数据
      </div>
    );
  }

  return (
    <div style={{ height: "100%" }}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        fitView
        attributionPosition="bottom-left"
      >
        <Background color="var(--color-border-subtle)" />
        <Controls />
      </ReactFlow>
    </div>
  );
}
