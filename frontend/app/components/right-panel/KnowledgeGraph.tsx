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
 * Build graph nodes and edges from character & scene data.
 * - Character nodes: circle layout (inner ring)
 * - Location nodes: circle layout (outer ring), from scene headings
 * - Edges: character ↔ location when character appears in a scene
 * Positions are fully deterministic (index-based) to avoid SSR mismatches.
 */
function buildGraph(
  characters: Record<string, unknown>[],
  scenes: Record<string, unknown>[],
): GraphData {
  const nodes: Node[] = [];
  const edges: Edge[] = [];

  // ── Character nodes (inner ring) ─────────────────────────────────
  const chCount = characters.length;
  for (let i = 0; i < chCount; i++) {
    const ch = characters[i];
    const chId = (ch.id as string) || `ch_${i}`;
    const angle = (2 * Math.PI * i) / Math.max(chCount, 1);
    nodes.push({
      id: chId,
      type: "default",
      data: { label: (ch.name as string) || chId },
      position: { x: Math.cos(angle) * 180, y: Math.sin(angle) * 180 },
      style: NODE_STYLE.character,
    });
  }

  // ── Location nodes (outer ring) + scene index map ────────────────
  const seenLocations = new Set<string>();
  const locs: string[] = [];
  // sceneIndex → location node id (for edge wiring)
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
      position: { x: Math.cos(angle) * 300 + 50, y: Math.sin(angle) * 300 },
      style: NODE_STYLE.location,
    });
  }

  // ── Edges: character appears in scene → edge to location ─────────
  const addedEdges = new Set<string>();

  for (let si = 0; si < scenes.length; si++) {
    const scene = scenes[si];
    const targetLocId = sceneLocMap.get(si);
    if (!targetLocId) continue;

    const elements = scene.elements as Array<Record<string, unknown>> | undefined;
    if (!elements) continue;

    for (const el of elements) {
      // A character_name in a dialogue_block means this character appears
      const chName = el.character_name;
      if (!chName) continue;

      // Try to match character by name or id
      for (const ch of characters) {
        const chId = ch.id as string;
        if (
          chId === chName ||
          (ch.name as string) === chName
        ) {
          const edgeKey = `${chId}->${targetLocId}`;
          if (!addedEdges.has(edgeKey)) {
            addedEdges.add(edgeKey);
            edges.push({
              id: edgeKey,
              source: chId,
              target: targetLocId,
              style: { stroke: "var(--color-border-emphasis)", strokeDasharray: "4 3" },
              label: `Scene ${si + 1}`,
              labelStyle: { fill: "var(--color-text-muted)", fontSize: 10 },
              labelBgStyle: { fill: "var(--color-bg-canvas)" },
            });
          }
        }
      }
    }
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
