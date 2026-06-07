import { create } from "zustand";
import { parse as parseYaml } from "yaml";
import type { KGNode, KGEdge } from "../api/tasks";

export interface SourceRef {
  document_id: string;
  chapter_id: string;
  offset: [number, number];
}

interface ScriptState {
  scriptId: string | null;
  title: string;
  sourceType: string;
  yaml: string | null;
  scenes: Record<string, unknown>[];
  characters: Record<string, unknown>[];
  knowledgeGraph: { nodes: KGNode[]; edges: KGEdge[] } | null;
  sourceRefMap: Map<string, SourceRef>;

  /** Load from the Script API response shape. */
  loadScript: (data: {
    script_id: string;
    title?: string;
    source_type?: string;
    script_yaml?: string | null;
    script_json?: Record<string, unknown> | null;
    characters_json?: Record<string, unknown>[] | null;
    knowledge_graph?: { nodes: KGNode[]; edges: KGEdge[] } | null;
  }) => void;
  /** Legacy: load from a Task response (still used for pending tasks). */
  loadFromTaskResponse: (data: {
    script_yaml?: string | null;
    script_json?: Record<string, unknown> | null;
    characters_json?: Record<string, unknown>[] | null;
    knowledge_graph?: { nodes: KGNode[]; edges: KGEdge[] } | null;
  }) => void;
  setKnowledgeGraph: (kg: { nodes: KGNode[]; edges: KGEdge[] } | null) => void;
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
      if (!sr?.chapter_id || !Array.isArray(sr.offset) || sr.offset.length !== 2) continue;

      // Primary key: positional index (always works regardless of explicit id)
      map.set(`${sceneId}_${ei}`, sr);

      // Secondary key: explicit element id if present (backward compat)
      const explicitId = el.id as string | undefined;
      if (explicitId) map.set(explicitId, sr);
    }
  }
  return map;
}

export const useScriptStore = create<ScriptState>((set) => ({
  scriptId: null,
  title: "",
  sourceType: "",
  yaml: null,
  scenes: [],
  characters: [],
  knowledgeGraph: null,
  sourceRefMap: new Map(),

  /** Primary load path for v3 Script API. */
  loadScript: (data) => {
    let scenes = (data.script_json?.scenes as Record<string, unknown>[]) ?? [];
    const characters = data.characters_json ?? [];
    const kg = data.knowledge_graph ?? null;

    if (scenes.length === 0 && data.script_yaml) {
      try {
        const parsed = parseYaml(data.script_yaml);
        if (parsed?.scenes && Array.isArray(parsed.scenes)) {
          scenes = parsed.scenes as Record<string, unknown>[];
        }
      } catch { /* keep empty */ }
    }

    const map = buildSourceRefMap(scenes);
    set({
      scriptId: data.script_id,
      title: data.title ?? "",
      sourceType: data.source_type ?? "",
      yaml: data.script_yaml ?? null,
      scenes,
      characters,
      knowledgeGraph: kg,
      sourceRefMap: map,
    });
  },

  /** Legacy loading from task response — used for pending/in-progress tasks. */
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

    const kg = data.knowledge_graph ?? null;
    const map = buildSourceRefMap(scenes);
    set({
      yaml: data.script_yaml ?? null,
      scenes,
      characters,
      knowledgeGraph: kg,
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
