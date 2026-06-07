# NovelScript Pipeline v0.3.0 改进方案规格说明书

> 基于对《永恒至尊》和《活着》两个转换输出的详细评估，本规格定义下一版本 pipeline 的改进目标、技术方案和验收标准。

---

## 目录

1. [总体目标](#1-总体目标)
2. [P0: 阻塞性问题](#2-p0-阻塞性问题)
3. [P1: 质量提升](#3-p1-质量提升)
4. [P2: 专业度](#4-p2-专业度)
5. [P3: 长期架构](#5-p3-长期架构)
6. [实施路线图](#6-实施路线图)
7. [测试计划](#7-测试计划)
8. [回滚与兼容性](#8-回滚与兼容性)

---

## 1. 总体目标

### 1.1 当前版本 (v0.2.0) 评估总结

| 指标 | 永恒至尊 | 活着_余华 | 行业基准 |
|------|---------|-----------|---------|
| 场景切分合理性 | 5/10 | 3/10 | ≥7 |
| 标题规范性 | 3/10 | 2/10 | ≥8 |
| 元素类型准确性 | 5/10 | 4/10 | ≥8 |
| 对白保留度 | 8/10 | 7/10 | ≥7 |
| 叙事框架完整性 | 6/10 | 2/10 | ≥7 |
| KG 覆盖与质量 | 8/10 | 7/10 | ≥7 |
| 加权综合 | **5.8/10** | **4.5/10** | ≥7 |

### 1.2 v0.3.0 目标

将两个测试样本的综合评分提升至 **≥7.5/10**，其中：
- 标题规范性 ≥ 9/10（通过自动化后处理保证）
- 元素类型准确性 ≥ 8/10
- 场景切分合理性 ≥ 7/10
- 叙事框架完整性 ≥ 7/10

### 1.3 设计原则

1. **后处理优先于 Prompt 调优**：凡可通过确定性算法修复的问题，不依赖 LLM prompt 黑盒调优
2. **不破坏 source_ref 链路**：所有后处理步骤必须保持或更新 source_ref
3. **向后兼容**：新增字段使用 Optional，旧版输出可被新版读取
4. **增量改进**：每项改进独立可测，不引入级联回归

---

## 2. P0: 阻塞性问题

### 2.1 全局唯一 Scene ID 分配

**现状问题**：
- `永恒至尊_out.yaml` 中 `s_002` 和 `s_003` 在 ch_02/ch_03 中重复出现
- `活着_余华_out.yaml` 中 `s_001`-`s_010` 跨章节重复
- 根因：converter.py 每次调用从 0 开始编号，未做全局协调

**改进方案**：

在 `pipeline.py` 的 `run_from_chapters()` 中增加全局 ID 分配器：

```python
# pipeline.py — 新增函数
def _assign_scene_ids(scenes_by_chapter: list[list[Scene]]) -> list[list[Scene]]:
    """Assign globally unique, sequential scene IDs across all chapters.

    Scene IDs follow the pattern ``s_{global_index:04d}``, e.g. s_0001, s_0002.
    IDs are assigned in chapter order; within a chapter, scenes keep their
    relative order.
    """
    global_idx = 1
    for chapter_scenes in scenes_by_chapter:
        for scene in chapter_scenes:
            scene.scene_id = f"s_{global_idx:04d}"
            global_idx += 1
    return scenes_by_chapter
```

`characters_present` 引用的是 KG node ID（如 `n_01`），无需更新。

**涉及文件**：
- `backend/cli/pipeline.py` — 在 converter 返回后、optimizer 调用前插入

**验收标准**：
- 同一 YAML 输出中所有 `scene_id` 唯一
- 场景 ID 按章节顺序递增
- 现有测试不回归

---

### 2.2 Scene Heading 标准化

**现状问题**：

```
# 不合格
外景 练武场 - 白天          # 中文前缀
河边 - 午后                  # 缺 INT/EXT
武学阁 - 日                  # 缺 INT/EXT + 中文时间
闪回 - 徐家田地 - 傍晚       # 非标准闪回标记
田里 / 茅屋 - 白天           # 两个地点混用
李家各处 - 几天后            # 缺 INT/EXT + 时间非标准
```

**标准格式定义**：

```
[INT./EXT.] LOCATION - TIME_OF_DAY [ - SPECIAL]
```

其中：
- `INT.` = 室内场景
- `EXT.` = 室外场景
- `INT./EXT.` = 同时包含室内外（如车内/车外）
- `TIME_OF_DAY` = `DAY` | `NIGHT` | `DUSK` | `DAWN` | `AFTERNOON` | `MORNING`
- `SPECIAL` = `FLASHBACK` | `FLASHFORWARD` | `DREAM` | `MONTAGE` | `CONTINUOUS` | `LATER` | `MOMENTS LATER`

**改进方案**：

##### A. Converter Prompt 约束

在 `converter.py` 的 `_PROMPT` 中替换 heading 指令：

```python
# converter.py — prompt 修改（原 L33-L34 替换为）
"""
每个场景必须包含标准 slug line (heading)，格式严格遵循：
  INT./EXT. LOCATION - TIME_OF_DAY

规则：
- 前缀用 INT. 或 EXT.，不能用中文"内景/外景"
- 时间用英文：DAY, NIGHT, DUSK, DAWN, AFTERNOON, MORNING
- 如果是回忆场景，在末尾添加 (FLASHBACK)：EXT. 徐家田地 - DUSK (FLASHBACK)
- 如果是梦境，添加 (DREAM)：INT. 李浮尘的脑海 - NIGHT (DREAM)
- 不要使用"闪回"、"回忆"等中文标记
- 不要在一个 heading 中使用两个地点（用 / 分隔）
- 时间跳跃用 LATER 或 CONTINUOUS：EXT. 后山山顶 - DAY (LATER)
"""
```

##### B. 确定性后处理函数

新增 `backend/cli/heading_normalizer.py`：

```python
"""Scene heading normalizer — deterministic post-processing for slug lines."""

from __future__ import annotations

import re

# Mapping from Chinese time-of-day to standard English
_TIME_MAP: dict[str, str] = {
    "白天": "DAY",
    "日": "DAY",
    "夜晚": "NIGHT",
    "夜": "NIGHT",
    "深夜": "NIGHT",
    "傍晚": "DUSK",
    "黄昏": "DUSK",
    "午后": "AFTERNOON",
    "下午": "AFTERNOON",
    "清晨": "DAWN",
    "早晨": "MORNING",
    "上午": "MORNING",
}

# Mapping from Chinese location prefixes to standard slug prefixes
_LOC_PREFIX_MAP: dict[str, str] = {
    "内景": "INT.",
    "外景": "EXT.",
}

# Internal location indicators (heuristic — presence of any word suggests INT.)
_INTERIOR_INDICATORS: list[str] = [
    "房间", "大厅", "屋里", "室内", "亭楼", "阁", "堂",
    "餐厅", "卧室", "厨房", "书房", "牢房", "密室", "青楼",
    "私塾", "店铺",
]

# Non-standard flashback markers to normalize
_FLASHBACK_MARKERS: list[str] = [
    "闪回 - ", "闪回-", "闪回：", "回忆 - ", "回忆：",
    "(闪回)", "（闪回）",
]


def normalize_heading(heading: str) -> str:
    """Normalize a single scene heading to standard slug-line format.

    Handles:
    - Chinese → English prefix (内景 → INT., 外景 → EXT.)
    - Chinese → English time-of-day (白天 → DAY, etc.)
    - Missing INT./EXT. prefix (heuristic detection)
    - Non-standard flashback markers → (FLASHBACK)
    - Multi-location slash merge

    Returns:
        Normalized heading string, e.g. ``EXT. 练武场 - DAY``.
    """
    original = heading.strip()

    # Step 1: Extract and normalize flashback markers
    flashback = False
    for marker in _FLASHBACK_MARKERS:
        if original.startswith(marker) or marker in original:
            flashback = True
            original = original.replace(marker, "").strip()
            # Also handle trailing Chinese markers
            original = re.sub(r"\s*[（(]闪回[）)]\s*", "", original)

    # Step 2: Detect existing INT./EXT. prefix
    prefix = None
    for cn_prefix, en_prefix in _LOC_PREFIX_MAP.items():
        if original.startswith(cn_prefix):
            prefix = en_prefix
            original = original[len(cn_prefix):].strip()
            break

    # Step 3: If no prefix, detect from location semantics
    if prefix is None:
        # Check for standard English prefixes already present
        m = re.match(r"^(INT\.|EXT\.|INT\./EXT\.)\s+", original)
        if m:
            prefix = m.group(1)
            original = original[m.end():].strip()
        else:
            # Heuristic: interior keywords → INT., else EXT.
            if any(indicator in original for indicator in _INTERIOR_INDICATORS):
                prefix = "INT."
            else:
                prefix = "EXT."

    # Step 4: Extract and normalize time-of-day
    # Pattern: "LOCATION - TIME" or "LOCATION - TIME (SPECIAL)" or just "LOCATION"
    time_part = "DAY"  # default
    special = ""
    location = original

    # Match trailing time patterns
    time_match = re.search(
        r"\s*[-—]\s*"
        r"([^\s(（]+)"
        r"(?:\s*[（(]([^)）]+)[）)])?$",
        original,
    )
    if time_match:
        location = original[:time_match.start()].strip()
        raw_time = time_match.group(1).strip()
        time_part = _TIME_MAP.get(raw_time, raw_time.upper())
        if time_match.group(2):
            special = time_match.group(2)

    # Step 5: Clean location (remove trailing punctuation, normalize spaces)
    location = re.sub(r"\s*/\s*", " / ", location).strip()

    # Step 6: Assemble
    if flashback:
        special = "FLASHBACK" if not special else f"FLASHBACK, {special}"

    if special:
        return f"{prefix} {location} - {time_part} ({special})"
    return f"{prefix} {location} - {time_part}"
```

##### C. 在 pipeline 中集成

```python
# pipeline.py — 在 exporter 调用前插入
from cli.heading_normalizer import normalize_heading

for scene in script.scenes:
    scene.heading = normalize_heading(scene.heading)
```

**涉及文件**：
- `backend/cli/heading_normalizer.py` — **新建**
- `backend/cli/converter.py` — prompt 修改
- `backend/cli/pipeline.py` — 集成调用

**验收标准**：
- 所有 heading 符合 `INT./EXT. LOCATION - TIME` 格式
- 中英文前缀全部转为英文
- 闪回标记统一为 `(FLASHBACK)`
- 单元测试覆盖所有已知的异常格式变体

---

### 2.3 叙事框架感知 (Narrative Frame Detection)

**现状问题**：
- 《活着》的双重时间框架（叙述者"我"→福贵讲述→闪回）被完全扁平化
- 输出中 ch_00 的 s_001-s_004（框架）与 s_005-s_009（闪回）没有层级区分
- flashback 场景在全局场景列表中与框架场景混排

**改进方案**：

##### A. 在 converter prompt 中增加层级指令

```python
# converter.py — 在 system prompt 中追加
"""
叙事层级规则（重要）：
如果你检测到以下模式，请在 heading 中明确标记：
1. 第一人称叙述者框架 → heading 以 "FRAME:" 开头
   例：FRAME: EXT. 乡间田野 - AFTERNOON
2. 角色回忆/讲述的往事 → heading 末尾添加 (FLASHBACK)
   例：EXT. 徐家田地 - DUSK (FLASHBACK)
3. 回忆中的回忆（嵌套闪回）→ 使用 (FLASHBACK WITHIN FLASHBACK)
4. 回到框架叙述 → heading 以 "FRAME:" 开头
   例：FRAME: EXT. 大树下 - AFTERNOON
"""
```

##### B. 后处理：场景层级分组

在 `pipeline.py` 中增加 `_classify_narrative_layers()`：

```python
def _classify_narrative_layers(scenes: list[Scene]) -> dict:
    """Detect and annotate narrative frame structure.

    Returns metadata for inclusion in the script output:
        {
            "has_frame_narrative": bool,
            "layers": [
                {"layer": "FRAME", "scene_ids": ["s_0001", "s_0002", ...]},
                {"layer": "FLASHBACK", "scene_ids": ["s_0005", ...]},
                ...
            ]
        }
    """
    layers = {"FRAME": [], "FLASHBACK": [], "FLASHBACK_NESTED": []}
    current_layer = "FRAME"

    for scene in scenes:
        heading = scene.heading
        if heading.startswith("FRAME:") or "FRAME:" in heading:
            current_layer = "FRAME"
            layers["FRAME"].append(scene.scene_id)
        elif "(FLASHBACK WITHIN FLASHBACK)" in heading:
            current_layer = "FLASHBACK_NESTED"
            layers["FLASHBACK_NESTED"].append(scene.scene_id)
        elif "(FLASHBACK)" in heading:
            current_layer = "FLASHBACK"
            layers["FLASHBACK"].append(scene.scene_id)
        else:
            layers[current_layer].append(scene.scene_id)

    has_frame = bool(layers["FLASHBACK"])  # FLASHBACK existence implies frame
    return {"has_frame_narrative": has_frame, "layers": layers}
```

这个元数据注入到 `Script.meta` 中：

```yaml
meta:
  narrative_structure:
    has_frame_narrative: true
    layers:
      FRAME: [s_0001, s_0002, s_0003, s_0004]
      FLASHBACK: [s_0005, ..., s_0030]
      FRAME_RETURN: [s_0031, s_0032]
```

##### C. Script.meta 扩展

在 `backend/cli/models.py` 中增加：

```python
class NarrativeLayer(BaseModel):
    """A narrative layer in the script structure."""
    layer: str = Field(..., description="FRAME, FLASHBACK, or FLASHBACK_NESTED")
    scene_ids: list[str] = Field(default_factory=list)

class ScriptMeta(BaseModel):
    """Extended metadata for the script output."""
    # ... existing fields ...
    narrative_structure: Optional[dict] = Field(
        None,
        description="Narrative layer classification: has_frame_narrative, layers"
    )
```

**涉及文件**：
- `backend/cli/converter.py` — prompt 修改
- `backend/cli/pipeline.py` — 增加 `_classify_narrative_layers()`
- `backend/cli/models.py` — ScriptMeta 扩展（可选）

**验收标准**：
- 《活着》输出的 `meta.narrative_structure` 非空
- FRAME 场景与 FLASHBACK 场景在 heading 中有明确区分
- 不影响纯线性叙事作品（永恒至尊不产生误报）

---

## 3. P1: 质量提升

### 3.1 内心独白元素类型自动修正

**现状问题**：
- 包含 `内心`、`心想`、`暗忖`、`心道` 等关键词的元素被错误标记为 `action`
- 应标记为 `dialogue` 并追加 `(V.O.)` parenthetical

**改进方案**：

新增 `backend/cli/element_fixer.py`：

```python
"""Element type fixer — post-processing corrections for common LLM type errors."""

from __future__ import annotations

import re

from cli.models import Element

# Patterns that indicate internal monologue (should be dialogue, not action)
_INTERNAL_MONOLOGUE_PATTERNS: list[re.Pattern] = [
    # 李浮尘内心：xxx
    re.compile(r"^(.{1,8})内心[：:]\s*(.+)"),
    # 李浮尘心中暗想：xxx / 李浮尘心想：xxx
    re.compile(r"^(.{1,8})(?:心中)?(?:暗想|心想|暗忖|心道|暗自\w+)[：:]\s*(.+)"),
    # xxx内心：xxx (无主语)
    re.compile(r"^内心[：:]\s*(.+)"),
    # 暗想：xxx / 心道：xxx
    re.compile(r"^(暗想|心想|暗忖|心道|暗骂)[：:]\s*(.+)"),
]

# Patterns that detect V.O.-worthy narration embedded in action
_VO_INDICATORS: list[str] = [
    "喃喃道", "喃喃自语", "自言自语道", "轻声说", "低声道",
    "默默道", "心里说", "对自己说",
]


def fix_element_types(elements: list[Element]) -> list[Element]:
    """Correct element type misclassifications in place.

    Fixes applied:
    1. Internal monologue marked as ``action`` → ``dialogue`` with ``(V.O.)``
    2. Spoken self-talk (喃喃自语) → ``dialogue``
    3. Dialogue with speaker embedded in content → split into character + dialogue

    Returns the modified elements list (mutated in place).
    """
    for elem in elements:
        if elem.type != "action":
            continue

        content = elem.content.strip()

        # Fix 1: Internal monologue patterns
        for pattern in _INTERNAL_MONOLOGUE_PATTERNS:
            m = pattern.match(content)
            if m:
                if m.lastindex and m.lastindex >= 2:
                    # Has separate speaker and monologue content
                    speaker = m.group(1).strip()
                    monologue = m.group(2).strip()
                    elem.type = "dialogue"
                    elem.content = f"{speaker} (V.O.): {monologue}"
                else:
                    # No explicit speaker
                    elem.type = "dialogue"
                    elem.content = f"(V.O.) {m.group(1).strip()}"
                break

        # Fix 2: Self-talk indicators
        for indicator in _VO_INDICATORS:
            if indicator in content:
                # Extract quoted speech if present
                quote_match = re.search(r"['""'「](.+?)['""'」]", content)
                if quote_match:
                    elem.type = "dialogue"
                    elem.content = f"{quote_match.group(1)}"

    return elements


def split_embedded_character(elements: list[Element]) -> list[Element]:
    """Split elements where the speaker name is embedded in content.

    Detects patterns like ``二喜(大喊)：苦根！`` and splits into:
        - type: character, content: 二喜
        - type: dialogue, content: 苦根！

    Also handles ``福贵(对牛)：今天有庆...`` and similar.
    """
    new_elements: list[Element] = []
    for elem in elements:
        if elem.type != "dialogue":
            new_elements.append(elem)
            continue

        # Pattern: "Name(emotion)：content" or "Name：content"
        match = re.match(
            r"^(.{1,12})\s*"
            r"(?:[（(]([^)）]{1,10})[）)])?\s*"
            r"[：:]\s*"
            r"(.+)$",
            elem.content,
        )
        if match and len(match.group(1)) <= 12:
            character_name = match.group(1).strip()
            parenthetical = match.group(2)
            dialogue_text = match.group(3).strip()

            # Only split if the "name" looks like a character, not a sentence start
            if _looks_like_character_name(character_name):
                char_elem = Element(
                    type="character",
                    content=character_name,
                    source_ref=elem.source_ref,
                )
                new_elements.append(char_elem)

                if parenthetical:
                    par_elem = Element(
                        type="parenthetical",
                        content=parenthetical,
                        source_ref=elem.source_ref,
                    )
                    new_elements.append(par_elem)

                dial_elem = Element(
                    type="dialogue",
                    content=dialogue_text,
                    source_ref=elem.source_ref,
                )
                new_elements.append(dial_elem)
                continue

        new_elements.append(elem)

    return new_elements


def _looks_like_character_name(text: str) -> bool:
    """Heuristic: does this text fragment look like a character name?"""
    # Character names are usually 2-4 Chinese characters, or known patterns
    if len(text) <= 1:
        return False
    if len(text) > 8:
        return False
    # Contains only Chinese characters (and maybe a period for titles)
    if not re.match(r"^[一-鿿·]+$", text):
        return False
    # Not a common dialogue opener
    common_openers = {"然后", "所以", "但是", "因为", "如果", "虽然", "不过"}
    if text in common_openers:
        return False
    return True
```

**涉及文件**：
- `backend/cli/element_fixer.py` — **新建**
- `backend/cli/pipeline.py` — 在 optimizer 后插入调用

**验收标准**：
- 《永恒至尊》s_005 中的 3 个内心独白被正确转为 `dialogue` + `(V.O.)`
- 《活着》中嵌入的 `二喜(大喊)：苦根！` 被拆分为 character + parenthetical + dialogue
- 单元测试：提供 20+ 个边界案例

---

### 3.2 微场景合并后处理

**现状问题**：
- 场景分布极不均：有的场景仅 2 个元素，有的 25 个
- 同一地点同时段的相邻场景应合并
- 元素过少的场景通常是 paragraph-group 边界而非戏剧边界

**改进方案**：

```python
# backend/cli/scene_merger.py — 新建

def merge_tiny_scenes(
    scenes: list[Scene],
    min_elements: int = 2,
    same_location_only: bool = True,
) -> list[Scene]:
    """Merge adjacent scenes with too few elements.

    Merging rules:
    1. Both scenes must be at the same location (if ``same_location_only``)
    2. Both scenes must have the same time_of_day (within tolerance)
    3. The second scene has fewer than ``min_elements`` elements
    4. Neither scene has ``(FLASHBACK)`` markers that differ

    Merged scenes keep the first scene's heading and scene_id.
    Elements are concatenated in order.
    """
    if len(scenes) <= 1:
        return scenes

    merged: list[Scene] = []
    for scene in scenes:
        if not merged:
            merged.append(scene)
            continue

        prev = merged[-1]

        # Check merge conditions
        can_merge = (
            len(scene.elements) < min_elements
            and (not same_location_only or prev.location == scene.location)
            and _time_compatible(prev.time_of_day, scene.time_of_day)
            and _flashback_compatible(prev.heading, scene.heading)
        )

        if can_merge:
            # Merge elements
            prev.elements.extend(scene.elements)
            # Update characters_present (union)
            for cid in scene.characters_present:
                if cid not in prev.characters_present:
                    prev.characters_present.append(cid)
        else:
            merged.append(scene)

    return merged


def _time_compatible(t1: str, t2: str) -> bool:
    """Check if two time-of-day values are compatible for merging."""
    if t1 == t2:
        return True
    # Compatible pairs
    compatible_pairs = {
        ("DAY", "MORNING"), ("DAY", "AFTERNOON"),
        ("NIGHT", "DUSK"), ("DUSK", "NIGHT"),
        ("DAY", "DUSK"),  # transitional
    }
    return (t1.upper(), t2.upper()) in compatible_pairs or \
           (t2.upper(), t1.upper()) in compatible_pairs


def _flashback_compatible(h1: str, h2: str) -> bool:
    """Two headings are compatible if they have the same flashback status."""
    has_fb1 = "FLASHBACK" in h1
    has_fb2 = "FLASHBACK" in h2
    return has_fb1 == has_fb2
```

**涉及文件**：
- `backend/cli/scene_merger.py` — **新建**
- `backend/cli/pipeline.py` — 在 heading_normalizer 之后、exporter 之前调用

**验收标准**：
- 永恒至尊：15场景 → 减少至 ≈10 场景（合并 5 个微场景）
- 活着：32场景 → 减少至 ≈18-20 场景
- 合并后的场景至少保留第一个场景的 source_ref 完整性

---

### 3.3 章节时间线顺序验证

**现状问题**：
- 《活着》输入章节 ch1→ch10→ch2，pipeline 未检测到时间线跳跃
- 导致输出的 chapter_summaries 时间线倒置

**改进方案**：

在 `pipeline.py` 中增加 `_validate_chapter_order()`：

```python
def _validate_chapter_order(chapters: list[Chapter]) -> dict:
    """Check if chapters are in chronological order.

    Detects:
    - Out-of-order chapter indices
    - Non-contiguous chapter sequences
    - Potential time-gaps between chapters

    Returns a warnings dict for inclusion in Script.meta.
    """
    warnings: list[str] = []
    indices = [ch.index for ch in chapters]

    # Check for non-monotonic indices
    for i in range(1, len(indices)):
        if indices[i] < indices[i - 1]:
            warnings.append(
                f"Chapter {chapters[i].title} (index {indices[i]}) appears after "
                f"chapter {chapters[i-1].title} (index {indices[i-1]}) — "
                f"possible timeline inversion"
            )

    # Check for gaps
    for i in range(1, len(indices)):
        gap = indices[i] - indices[i - 1]
        if gap > 1:
            warnings.append(
                f"Gap of {gap - 1} chapter(s) between chapter "
                f"{chapters[i-1].title} and {chapters[i].title}"
            )

    return {
        "chapter_count": len(chapters),
        "chapter_indices": [ch.index for ch in chapters],
        "is_monotonic": indices == sorted(indices),
        "warnings": warnings,
    }
```

这个结果注入 `Script.meta`：

```yaml
meta:
  chapter_validation:
    chapter_count: 3
    chapter_indices: [1, 10, 2]
    is_monotonic: false
    warnings:
      - "Chapter 10 appears after chapter 1 — possible timeline inversion"
```

**涉及文件**：
- `backend/cli/pipeline.py` — 在 `_load_chapters()` 后调用

**验收标准**：
- 《活着》输入会产生 `is_monotonic: false` 和明确的警告信息
- 《永恒至尊》输入会产生 `is_monotonic: true` 且无警告

---

## 4. P2: 专业度

### 4.1 KG 情感权重细化

**现状问题**：
- 几乎所有权重为 1.0 或 0.8
- `lover_of: 0.7` 和 `enemy_of: 0.9` 是少数有区分度的边
- 缺少对情感强度的细粒度衡量

**改进方案**：

在 `graphrag_builder.py` 的 prompt 中修改权重指令：

```python
# graphrag_builder.py — prompt 修改
"""
关系权重 (weight) 规则（0.0-1.0）：
- 1.0：确定且强烈的关系（血亲、核心敌友）
- 0.8-0.9：确定但中等强度的关系（远亲、普通朋友）
- 0.5-0.7：隐含或单向的关系（单恋、竞争）
- 0.2-0.4：推测或微弱的关系（短暂互动、间接关联）

示例：
- 福贵→凤霞 family_of 1.0（父女，核心血亲）
- 福贵→有庆 family_of 0.9（父子，但在叙事中有隔阂）
- 李云河→关雪 lover_of 0.3（单方面的嫉妒/爱慕，非双向）
- 李天寒→关岳 friend_of 0.3（表面友好，实际已破裂）
"""
```

**涉及文件**：
- `backend/cli/graphrag_builder.py` — prompt 修改

**验收标准**：
- 输出中至少 30% 的边权重非 1.0
- `family_of` 边有区分（核心家庭 1.0 vs 姻亲 0.7-0.8）
- 单向情感关系（单恋、嫉妒）权重 ≤ 0.5

---

### 4.2 对白原文保留约束强化

**现状问题**：
- 《永恒至尊》高潮战斗场景中，LLM 生成了原文不存在的大量对白（source_ref = null）
- 部分对话被不必要的简化或改写

**改进方案**：

在 `converter.py` prompt 中增加：

```python
"""
对白保留规则（严格遵守）：
1. 原文中的对话，必须逐字保留，不得改写或简化
2. 不要添加原文没有的对话
3. 不要将原文的对话"现代化"或"合理化"
4. 如果原文的对话不完整或有歧义，保持原样，不要补充
5. 仅在原文的叙述性描写需要转换为对白时，才可创建新的 dialogue 元素
   （例如："他骂了几句" → 根据上下文创建合理的骂辞）
6. 创建的新对白必须在 source_ref 中标记 confidence: "inferred"
"""
```

同时在 element_fixer.py 中增加 source_ref null 检测：

```python
def flag_missing_source_refs(elements: list[Element]) -> list[dict]:
    """Identify elements with null source_ref (potentially hallucinated)."""
    flagged = []
    for i, elem in enumerate(elements):
        if elem.source_ref is None:
            flagged.append({
                "index": i,
                "type": elem.type,
                "content_preview": elem.content[:80],
                "severity": "warning" if elem.type == "action" else "error",
            })
    return flagged
```

**涉及文件**：
- `backend/cli/converter.py` — prompt 修改
- `backend/cli/element_fixer.py` — 增加 null-ref flag

**验收标准**：
- 复测《永恒至尊》时，s_03 战斗场景的 null source_ref 数量减少至 ≤2
- 所有新增对白标记 `confidence: "inferred"`

---

### 4.3 Fountain 格式导出

**现状问题**：
- pipeline 导出 YAML 和 JSON，但这两种格式不能被 Final Draft / Highland 2 / Fade In 等专业编剧软件直接导入
- Fountain 是行业标准交换格式（`.fountain` 纯文本）

**改进方案**：

新增 `backend/cli/fountain_exporter.py`：

```python
"""Fountain exporter — converts a Script to Fountain 1.1 format."""

from cli.models import Element, Scene, Script


def to_fountain(script: Script) -> str:
    """Convert a Script to Fountain-formatted text.

    Fountain 1.1 spec: https://fountain.io/syntax

    Output format:
        EXT. 练武场 - DAY

        李云河一剑斩出。

                      李云河
              李浮尘，再练十年你也不是我对手。

        砰！李浮尘被击飞出去。

        ===

        INT. 李浮尘的房间 - NIGHT

        ...
    """
    lines: list[str] = []

    # Title page
    lines.append(f"Title: {script.meta.get('source_file', 'Untitled')}")
    lines.append(f"Credit: Adapted by NovelScript Pipeline")
    lines.append(f"Source: Novel → Script Conversion")
    lines.append("")
    lines.append("===")
    lines.append("")

    for scene in script.scenes:
        # Scene heading
        lines.append(scene.heading)
        lines.append("")

        for elem in scene.elements:
            lines.extend(_render_element(elem))

        # Scene separator
        lines.append("")
        lines.append("===")
        lines.append("")

    return "\n".join(lines)


def _render_element(elem: Element) -> list[str]:
    """Render a single element as Fountain-formatted lines."""
    content = elem.content.strip()

    if elem.type == "heading":
        return [content, ""]

    if elem.type == "character":
        return [content.upper().rjust(40), ""]

    if elem.type == "dialogue":
        return [content, ""]

    if elem.type == "parenthetical":
        return [f"({content})", ""]

    if elem.type == "transition":
        return [f"> {content}", ""]

    if elem.type == "lyric":
        return [f"~ {content}", ""]

    # action, note, and default
    return [content, ""]
```

**涉及文件**：
- `backend/cli/fountain_exporter.py` — **新建**
- `backend/cli/pipeline.py` — 增加 `--format fountain` 选项

**验收标准**：
- `.fountain` 输出可在 Highland 2 和 VS Code Fountain 插件中正确渲染
- 场景标题、角色名、对白、动作块均正确格式化
- 现有 YAML/JSON 导出不受影响

---

## 5. P3: 长期架构

### 5.1 体裁感知转换模板

**改进思路**（本版本只做设计，不下发实现）：

在 converter prompt 中根据体裁选择不同的子策略：

| 体裁 | 转换策略 | 场景密度 | 对白策略 | 叙事保留度 |
|------|---------|---------|---------|-----------|
| 仙侠/玄幻 | 动作优先 | 中 (3-5/章) | 功能性保留 | 低（类型化） |
| 严肃文学 | 语调优先 | 低 (2-4/章) | 逐字保留+潜台词 | 高（文学性） |
| 悬疑/推理 | 信息不对称 | 中 (3-5/章) | 精确保留 | 高（线索完整） |
| 言情 | 情感优先 | 中 (3-5/章) | 保留+情感标记 | 中 |

体裁检测可通过：
1. 用户传入 `-s` / `--style` 参数（已存在）
2. LLM 自动体裁分类（pipeline 前序阶段）
3. 关键词匹配作为后备

### 5.2 多 Pass 迭代优化

**设计思路**（本版本不做实现）：

将当前 single-pass optimizer 改为 multi-pass：

```
Pass 1: Structural — scene boundaries, heading normalization
Pass 2: Dialogue — subtext retention, voice consistency
Pass 3: Pacing — scene length balance, micro-scene merge
Pass 4: Tone — mood consistency, atmosphere preservation
```

每个 pass 是一个独立的 optimizer 调用，有自己的 prompt 和验证逻辑。Passes 串行执行，后续 pass 的输入是前一个 pass 的输出。

### 5.3 质量自动评分

**设计思路**（本版本不做实现）：

新增 `backend/cli/quality_scorer.py`：

```python
def score_script(script: Script) -> dict:
    """Compute quality scores for a completed script."""
    return {
        "heading_standardization_rate": _heading_score(script),
        "dialogue_to_action_ratio": _dialogue_ratio(script),
        "scene_size_variance": _scene_variance(script),
        "character_presence_distribution": _char_distribution(script),
        "null_source_ref_ratio": _null_ref_ratio(script),
        "kg_edge_weight_variance": _kg_weight_variance(script),
        "overall": ...  # weighted composite
    }
```

---

## 6. 实施路线图

### Phase 1: 后处理管线 (预计 4-6 小时)

```
[converter → scenes] → heading_normalizer → element_fixer → scene_merger → [optimizer] → [exporter]
```

**交付物**：
1. `heading_normalizer.py` — 含单元测试
2. `element_fixer.py` — 含单元测试
3. `scene_merger.py` — 含单元测试
4. `pipeline.py` 集成变更

### Phase 2: Prompt 优化 (预计 2-3 小时)

**交付物**：
1. `converter.py` prompt 更新（heading 格式 + 叙事层级 + 对白保留）
2. `graphrag_builder.py` prompt 更新（边权重）
3. `optimizer.py` prompt 更新（潜台词保护）

### Phase 3: 结构级改进 (预计 3-4 小时)

**交付物**：
1. 全局 scene_id 分配
2. 叙事框架检测与 meta 输出
3. 章节时间线验证

### Phase 4: 导出增强 (预计 2 小时)

**交付物**：
1. `fountain_exporter.py`
2. CLI `--format fountain` 选项

### Phase 5: 回归测试与样本复测 (预计 2-3 小时)

**交付物**：
1. 现有 158 测试全部通过
2. 使用 v0.3.0 重新转换《永恒至尊》和《活着》
3. 对比 v0.2.0 输出，验证改进效果

---

## 7. 测试计划

### 7.1 单元测试

| 模块 | 测试数 | 覆盖重点 |
|------|--------|---------|
| `heading_normalizer.py` | 15+ | 中文→英文前缀、闪回标记、时间格式、边界case |
| `element_fixer.py` | 20+ | 内心独白检测、speaker拆分、V.O.标记 |
| `scene_merger.py` | 10+ | 同地点合并、时间兼容性、不合并case |
| `fountain_exporter.py` | 8+ | 格式正确性、元素渲染 |

### 7.2 集成测试

1. **完整 pipeline 运行**（同时运行永恒至尊和活着）
2. **scene_id 全局唯一性检查**
3. **heading 格式合规检查**
4. **source_ref 链路完整性**（后处理不破坏追踪）

### 7.3 回归测试

- 现有 158 个测试 100% 通过
- `uv run pytest` 零失败零跳过

---

## 8. 回滚与兼容性

### 8.1 向后兼容

- `Script.meta` 新增字段均为 Optional
- 旧版 YAML 输出可被新版 `heading_normalizer` 作为输入处理
- `source_ref` 结构不变

### 8.2 CLI 兼容

- 现有 CLI 参数保持不变
- `--format fountain` 为新增选项，默认行为不变

### 8.3 数据库兼容

- Scene 模型不变
- KG 模型不变
- 新增 `narrative_structure` 字段仅在 YAML meta 中，不影响 DB schema

---

## 附录 A: 关键文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `backend/cli/heading_normalizer.py` | **新建** | 场景标题标准化 |
| `backend/cli/element_fixer.py` | **新建** | 元素类型修正 |
| `backend/cli/scene_merger.py` | **新建** | 微场景合并 |
| `backend/cli/fountain_exporter.py` | **新建** | Fountain 格式导出 |
| `backend/cli/pipeline.py` | **修改** | 全局 scene_id + 框架检测 + 时间线验证 + 集成调用 |
| `backend/cli/converter.py` | **修改** | Prompt 更新（heading + 对白 + 叙事层级） |
| `backend/cli/optimizer.py` | **修改** | Prompt 更新（潜台词保护） |
| `backend/cli/graphrag_builder.py` | **修改** | Prompt 更新（边权重） |
| `backend/cli/models.py` | **修改**（可选） | NarrativeStructure 模型 |

## 附录 B: 评估基线数据

用于 v0.3.0 发布后的效果对比：

| 指标 | 永恒至尊 v0.2.0 | 活着 v0.2.0 | v0.3.0 目标 |
|------|----------------|-------------|------------|
| scene_id 唯一性 | ❌ 冲突 | ❌ 冲突 | ✅ 100% 唯一 |
| heading 标准率 | 0% (0/15) | 9% (3/32) | ≥95% |
| 内心独白修正率 | 0% (0/~8) | 0% (0/~5) | ≥90% |
| 微场景合并率 | 0% | 0% | 场景数减少 ≥25% |
| 对白逐字保留率 | ~90% | ~95% | ≥95% |
| 编造对白(null ref)率 | ~30% | ~5% | ≤5% |
| 时间线检测 | 无 | 无 | 检测并报告 |
| 框架结构 | 无 | 扁平化 | 检测并标记 |
