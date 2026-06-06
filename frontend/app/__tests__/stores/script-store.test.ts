import { describe, it, expect, beforeEach } from "vitest";
import { useScriptStore } from "../../stores/script-store";

beforeEach(() => {
  useScriptStore.getState().clearScript();
});

describe("script-store", () => {
  describe("loadFromTaskResponse", () => {
    it("populates yaml, scenes, and characters from task payload", () => {
      const payload = {
        script_yaml: "scenes:\n  - title: Test",
        script_json: {
          scenes: [
            {
              scene_id: "s1",
              heading: { location: "INT. HOUSE" },
              elements: [
                {
                  id: "el_1",
                  type: "action",
                  text: "John enters.",
                  source_ref: {
                    chapter_id: "ch_01",
                    offset: [120, 145],
                    document_id: "doc_1",
                  },
                },
              ],
            },
          ],
        },
        characters_json: [{ id: "c1", name: "John" }],
      };

      useScriptStore.getState().loadFromTaskResponse(payload);

      const s = useScriptStore.getState();
      expect(s.yaml).toBe("scenes:\n  - title: Test");
      expect(s.scenes).toHaveLength(1);
      expect(s.scenes[0].scene_id).toBe("s1");
      expect(s.characters).toHaveLength(1);
      expect(s.characters[0].name).toBe("John");
    });

    it("handles null/missing fields gracefully", () => {
      useScriptStore.getState().loadFromTaskResponse({});
      const s = useScriptStore.getState();
      expect(s.yaml).toBeNull();
      expect(s.scenes).toEqual([]);
      expect(s.characters).toEqual([]);
      expect(s.sourceRefMap.size).toBe(0);
    });
  });

  describe("sourceRefMap", () => {
    it("builds elementId → SourceRef index from scenes", () => {
      const payload = {
        script_json: {
          scenes: [
            {
              scene_id: "s1",
              elements: [
                {
                  id: "el_a",
                  source_ref: { chapter_id: "ch_01", offset: [0, 50], document_id: "d1" },
                },
              ],
            },
            {
              scene_id: "s2",
              elements: [
                {
                  id: "el_b",
                  source_ref: { chapter_id: "ch_02", offset: [200, 300], document_id: "d1" },
                },
                {
                  id: "el_c",
                  // no source_ref — should be skipped
                },
              ],
            },
          ],
        },
      };
      useScriptStore.getState().loadFromTaskResponse(payload);

      const map = useScriptStore.getState().sourceRefMap;
      // 2 elements with source_ref × 2 keys each (id + positional fallback) = 4
      expect(map.size).toBe(4);
      expect(map.get("el_a")).toEqual({
        chapter_id: "ch_01",
        offset: [0, 50],
        document_id: "d1",
      });
      expect(map.get("el_b")!.offset).toEqual([200, 300]);
      expect(map.has("el_c")).toBe(false);
    });

    it("skips source_ref without chapter_id", () => {
      const payload = {
        script_json: {
          scenes: [
            {
              scene_id: "s1",
              elements: [
                {
                  id: "el_bad",
                  source_ref: { offset: [0, 10] }, // missing chapter_id
                },
              ],
            },
          ],
        },
      };
      useScriptStore.getState().loadFromTaskResponse(payload);
      expect(useScriptStore.getState().sourceRefMap.size).toBe(0);
    });
  });

  describe("setYaml", () => {
    it("replaces the yaml string", () => {
      useScriptStore.getState().setYaml("new yaml content");
      expect(useScriptStore.getState().yaml).toBe("new yaml content");
    });
  });

  describe("clearScript", () => {
    it("resets all fields", () => {
      useScriptStore.getState().loadFromTaskResponse({
        script_yaml: "test",
        script_json: { scenes: [] },
        characters_json: [],
      });
      useScriptStore.getState().clearScript();
      const s = useScriptStore.getState();
      expect(s.yaml).toBeNull();
      expect(s.scenes).toEqual([]);
      expect(s.characters).toEqual([]);
      expect(s.sourceRefMap.size).toBe(0);
    });
  });
});
