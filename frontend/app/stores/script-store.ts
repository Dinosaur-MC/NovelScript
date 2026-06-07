import { create } from "zustand";
import { parse as parseYaml } from "yaml";
import type { KGNode, KGEdge } from "../api/tasks";

export interface SourceRef {
  document_id: string;
  chapter_id: string;
  offset: [number, number];
}

interface ScriptState {
  yaml: string | null;
  scenes: Record<string, unknown>[];
  characters: Record<string, unknown>[];
  /** Full knowledge graph from the backend (all node types + edges). */
  knowledgeGraph: { nodes: KGNode[]; edges: KGEdge[] } | null;
  /** elementId → SourceRef for O(1) forward trace lookup */
  sourceRefMap: Map<string, SourceRef>;

  loadFromTaskResponse: (data: {
    script_yaml?: string | null;
    script_json?: Record<string, unknown> | null;
    characters_json?: Record<string, unknown>[] | null;
  }) => void;
  setKnowledgeGraph: (kg: { nodes: KGNode[]; edges: KGEdge[] } | null) => void;
  /** Update yaml and re-parse scenes for live preview. */
  updateYaml: (yaml: string) => void;
  setYaml: (yaml: string) => void;
  clearScript: () => void;
}

function buildSourceRefMap(scenes: Record<string, unknown>[]): Map<string, SourceRef> {
  const map = new Map<string, SourceRef>();
  for (const scene of scenes) {
    const sceneId = scene.scene_id as string;
    const elements = scene.elements as Array<Record<string, unknown>> | undefined;
    if (!elements) continue;
    for (let ei = 0; ei < elements.length; ei++) {
      const el = elements[ei];
      const sr = el.source_ref as SourceRef | undefined | null;
      if (!sr || !sr.chapter_id || !Array.isArray(sr.offset) || sr.offset.length !== 2) continue;

      // Register by element's own id (primary key — from YAML/backend)
      const id = (el.id ?? `${sceneId}_${el.type}`) as string;
      map.set(id, sr);

      // Also register by positional index (fallback for ScriptPreview click handler)
      map.set(`${sceneId}_${ei}`, sr);
    }
  }
  return map;
}

export const useScriptStore = create<ScriptState>((set) => ({
  yaml: null,
  scenes: [],
  characters: [],
  knowledgeGraph: null,
  sourceRefMap: new Map(),

  loadFromTaskResponse: (data) => {
    let scenes = (data.script_json?.scenes as Record<string, unknown>[]) ?? [];
    const characters = data.characters_json ?? [];

    // If script_json has no scenes but script_yaml exists, parse YAML for preview
    if (scenes.length === 0 && data.script_yaml) {
      try {
        const parsed = parseYaml(data.script_yaml);
        if (parsed?.scenes && Array.isArray(parsed.scenes)) {
          scenes = parsed.scenes as Record<string, unknown>[];
        }
      } catch { /* keep empty scenes on parse failure */ }
    }

    const map = buildSourceRefMap(scenes);
    set({
      yaml: data.script_yaml ?? null,
      scenes,
      characters,
      sourceRefMap: map,
    });
  },

  setKnowledgeGraph: (kg) => set({ knowledgeGraph: kg }),

  setYaml: (yaml) => set({ yaml }),

  /** Update yaml and re-parse scenes for live preview in the right panel.
   *  Uses the `yaml` library for proper parsing. On parse failure,
   *  keeps the previous scenes to avoid preview flicker during edits. */
  updateYaml: (yamlText) => {
    try {
      const parsed = parseYaml(yamlText);
      if (parsed && typeof parsed === "object") {
        const scenes = (parsed as Record<string, unknown>).scenes;
        if (scenes && Array.isArray(scenes)) {
          const sceneArr = scenes as Record<string, unknown>[];
          const sourceRefMap = buildSourceRefMap(sceneArr);
          set({ yaml: yamlText, scenes: sceneArr, sourceRefMap });
          return;
        }
      }
    } catch {
      // Keep current scenes on parse failure (incomplete mid-edit YAML)
    }
    // Text changed but couldn't parse — still update yaml string
    set({ yaml: yamlText });
  },

  clearScript: () =>
    set({ yaml: null, scenes: [], characters: [], knowledgeGraph: null, sourceRefMap: new Map() }),
}));
