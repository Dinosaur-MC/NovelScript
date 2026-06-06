import { create } from "zustand";

export interface SourceRef {
  document_id: string;
  chapter_id: string;
  offset: [number, number];
}

interface ScriptState {
  yaml: string | null;
  scenes: Record<string, unknown>[];
  characters: Record<string, unknown>[];
  /** elementId → SourceRef for O(1) forward trace lookup */
  sourceRefMap: Map<string, SourceRef>;

  loadFromTaskResponse: (data: {
    script_yaml?: string | null;
    script_json?: Record<string, unknown> | null;
    characters_json?: Record<string, unknown>[] | null;
  }) => void;
  setYaml: (yaml: string) => void;
  clearScript: () => void;
}

function buildSourceRefMap(scenes: Record<string, unknown>[]): Map<string, SourceRef> {
  const map = new Map<string, SourceRef>();
  for (const scene of scenes) {
    const elements = scene.elements as Array<Record<string, unknown>> | undefined;
    if (!elements) continue;
    for (const el of elements) {
      const sr = el.source_ref as SourceRef | undefined | null;
      const id = (el.id ?? `${scene.scene_id}_${el.type}`) as string;
      if (sr && sr.chapter_id && Array.isArray(sr.offset) && sr.offset.length === 2) {
        map.set(id, sr);
      }
    }
  }
  return map;
}

export const useScriptStore = create<ScriptState>((set) => ({
  yaml: null,
  scenes: [],
  characters: [],
  sourceRefMap: new Map(),

  loadFromTaskResponse: (data) => {
    const scenes = (data.script_json?.scenes as Record<string, unknown>[]) ?? [];
    const characters = data.characters_json ?? [];
    const map = buildSourceRefMap(scenes);
    set({
      yaml: data.script_yaml ?? null,
      scenes,
      characters,
      sourceRefMap: map,
    });
  },

  setYaml: (yaml) => set({ yaml }),

  clearScript: () =>
    set({ yaml: null, scenes: [], characters: [], sourceRefMap: new Map() }),
}));
