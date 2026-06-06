import { useMemo } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  type Node,
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

export function KnowledgeGraph() {
  const characters = useScriptStore((s) => s.characters);
  const scenes = useScriptStore((s) => s.scenes);

  // Extract nodes from characters + locations found in scenes.
  // Positions are deterministic (index-based circle layout) to avoid
  // SSR hydration mismatch from Math.random().
  const initialNodes = useMemo(() => {
    const nodes: Node[] = [];

    // Character nodes — arrange in a circle
    const chCount = characters.length;
    for (let i = 0; i < chCount; i++) {
      const ch = characters[i];
      const angle = (2 * Math.PI * i) / Math.max(chCount, 1);
      nodes.push({
        id: ch.id as string,
        type: "default",
        data: { label: (ch.name as string) || (ch.id as string) },
        position: { x: Math.cos(angle) * 180, y: Math.sin(angle) * 180 },
        style: NODE_STYLE.character,
      });
    }

    // Location nodes from scene headings — arrange in a second ring
    const seenLocations = new Set<string>();
    const locs: string[] = [];
    for (const scene of scenes) {
      const heading = scene.heading as Record<string, string> | undefined;
      const loc = heading?.location;
      if (loc && !seenLocations.has(loc)) {
        seenLocations.add(loc);
        locs.push(loc);
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

    return nodes;
  }, [characters, scenes]);

  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);

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
