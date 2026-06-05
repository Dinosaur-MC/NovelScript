"""Scene optimizer — cross-scene consistency and quality improvement.

Uses the Pro model to review all converted scenes and fix:
- Character arc inconsistencies (e.g. personality drift)
- Location continuity errors (teleportation without transition)
- Timeline contradictions (events out of order)
- Dialogue voice consistency

The optimizer produces a revised list of Scene objects.
"""

from __future__ import annotations

import json
import logging
import textwrap

from langchain_core.messages import HumanMessage, SystemMessage

from cli.llm_router import get_llm
from cli.models import Element, KnowledgeGraph, Scene

logger = logging.getLogger(__name__)

MAX_RETRIES = 2

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = textwrap.dedent("""\
你是一个剧本质量控制专家。你需要检查并修正一组剧本场景中的一致性问题。

检查要点：
1. **人物弧光一致性**: 同一角色的性格、语气、行为是否前后一致
2. **地点连续性**: 场景之间的地点切换是否合理，有无跳跃
3. **时间线**: 时间顺序是否正确，有无倒错
4. **对白风格**: 各角色的对白风格是否统一，有无串词

修正时：
- 仅修正明显的不一致之处，不要过度改写
- 保留原文的风格和内容精髓
- 如果需要修改元素内容，保留原有元素的类型和结构

你必须以严格的 JSON 数组格式输出修正后的场景列表，格式与输入相同：
```json
[
  {
    "scene_id": "s_001",
    "heading": "...",
    "location": "...",
    "time_of_day": "...",
    "elements": [...],
    "characters_present": [...],
    "optimization_notes": ["修正说明1", "修正说明2"]
  }
]
```

注意 optimization_notes 字段记录了你对该场景所做的修改说明。
""")

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def optimize(scenes: list[Scene], kg: KnowledgeGraph) -> list[Scene]:
    """Optimize scenes for cross-scene consistency.

    Args:
        scenes: The list of scenes to optimize.
        kg: Knowledge graph with character/location information.

    Returns:
        Optimized list of Scene objects (original list on failure).
    """
    if not scenes:
        logger.info("No scenes to optimize — returning empty list.")
        return []

    llm = get_llm("consistency_check", temperature=0.2)

    # Serialize scenes to JSON for the prompt
    input_json = _serialize_scenes(scenes)
    kg_summary = _summarize_kg(kg)

    for attempt in range(1 + MAX_RETRIES):
        try:
            raw_json = _call_llm(llm, input_json, kg_summary, attempt)
            optimized = _parse_and_validate(raw_json)
            logger.info("Optimizer: %d scene(s) processed.", len(optimized))
            return optimized
        except Exception as exc:
            logger.warning(
                "Optimizer attempt %d/%d failed: %s",
                attempt + 1,
                1 + MAX_RETRIES,
                exc,
            )
            if attempt >= MAX_RETRIES:
                logger.exception("Optimizer: all retries exhausted — returning original scenes.")
                return scenes

    return scenes


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _serialize_scenes(scenes: list[Scene]) -> str:
    """Convert scenes to a compact JSON string for the prompt."""
    data = []
    for s in scenes:
        data.append({
            "scene_id": s.scene_id,
            "heading": s.heading,
            "location": s.location,
            "time_of_day": s.time_of_day,
            "elements": [{"type": e.type, "content": e.content} for e in s.elements],
            "characters_present": s.characters_present,
        })
    return json.dumps(data, ensure_ascii=False, indent=2)


def _summarize_kg(kg: KnowledgeGraph) -> str:
    """Brief KG summary for the optimizer prompt."""
    if not kg.nodes:
        return ""
    chars = [n for n in kg.nodes if n.node_type == "character"]
    lines = ["人物参考："]
    for c in chars:
        lines.append(f"  {c.name} (traits: {c.properties.get('traits', [])})")
    return "\n".join(lines)


def _call_llm(llm, scenes_json: str, kg_summary: str, attempt: int) -> str:
    """Invoke Pro model for consistency check."""
    user_prompt = (
        f"请检查以下剧本场景的一致性并进行修正：\n\n"
        f"{kg_summary}\n\n"
        f"【场景列表】\n{scenes_json[:12000]}"
    )
    if attempt > 0:
        user_prompt = (
            f"上一次优化结果不符合 JSON 格式要求。请严格按照 JSON Schema 重新输出。\n\n"
            + user_prompt
        )

    messages = [
        SystemMessage(content=_SYSTEM_PROMPT),
        HumanMessage(content=user_prompt),
    ]
    resp = llm.invoke(messages)
    raw: str = resp.content.strip()  # type: ignore[union-attr]

    if "```json" in raw:
        raw = raw.split("```json")[1].split("```")[0].strip()
    elif "```" in raw:
        raw = raw.split("```")[1].split("```")[0].strip()

    return raw


def _parse_and_validate(raw_json: str) -> list[Scene]:
    """Parse optimizer JSON output and validate as list[Scene]."""
    data = json.loads(raw_json)
    if not isinstance(data, list):
        data = [data]

    scenes: list[Scene] = []
    for s in data:
        elements = [
            Element(
                type=el["type"],
                content=el["content"],
                source_ref=el.get("source_ref"),
            )
            for el in s.get("elements", [])
        ]
        scene = Scene(
            scene_id=s.get("scene_id", ""),
            heading=s.get("heading", ""),
            location=s.get("location", ""),
            time_of_day=s.get("time_of_day", ""),
            elements=elements,
            characters_present=s.get("characters_present", []),
        )
        scenes.append(scene)

    return scenes
