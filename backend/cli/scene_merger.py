"""Scene merger — merge adjacent micro-scenes that shouldn't be separate.

Detects adjacent scenes that were split by the LLM at paragraph-group
boundaries rather than true dramatic boundaries, and merges them back.

Merging rules:
1. Both scenes must be at the same location (if ``same_location_only``)
2. Both scenes must have compatible time-of-day
3. The second scene has fewer than ``min_elements`` elements
4. Neither scene has conflicting special markers (FLASHBACK, DREAM, etc.)
"""

from __future__ import annotations

from cli.models import Scene


def merge_tiny_scenes(
    scenes: list[Scene],
    min_elements: int = 2,
    same_location_only: bool = True,
) -> list[Scene]:
    """Merge adjacent scenes with too few elements.

    Merged scenes keep the first scene's heading and scene_id.
    Elements are concatenated in order.
    Characters_present is the union of both scenes.
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
            and (not same_location_only or _same_location(prev, scene))
            and _time_compatible(prev.time_of_day, scene.time_of_day)
            and _special_compatible(prev.heading, scene.heading)
        )

        if can_merge:
            # Merge elements
            prev.elements.extend(scene.elements)
            # Update characters_present (union)
            for cid in scene.characters_present:
                if cid not in prev.characters_present:
                    prev.characters_present.append(cid)
            # Update source_ref if the merged scene had one
            if scene.elements and scene.elements[0].source_ref:
                # Keep original scene's heading/ID but note merge
                pass
        else:
            merged.append(scene)

    return merged


def _same_location(a: Scene, b: Scene) -> bool:
    """Check if two scenes are at the same location."""
    aloc = a.location.strip().lower()
    bloc = b.location.strip().lower()
    if not aloc or not bloc:
        return False
    return aloc == bloc


def _time_compatible(t1: str, t2: str) -> bool:
    """Check if two time-of-day values are compatible for merging."""
    t1u = t1.upper().strip()
    t2u = t2.upper().strip()
    if t1u == t2u:
        return True
    compatible_pairs = {
        ("DAY", "MORNING"), ("DAY", "AFTERNOON"),
        ("NIGHT", "DUSK"), ("DUSK", "NIGHT"),
        ("DAY", "DUSK"),  # transitional
        ("MORNING", "AFTERNOON"),  # same part of day
        ("DAWN", "MORNING"),  # early morning
    }
    return (t1u, t2u) in compatible_pairs or (t2u, t1u) in compatible_pairs


def _special_compatible(h1: str, h2: str) -> bool:
    """Two headings are compatible if they have the same flashback/dream status."""
    has_fb1 = "FLASHBACK" in h1.upper()
    has_fb2 = "FLASHBACK" in h2.upper()
    has_dr1 = "DREAM" in h1.upper()
    has_dr2 = "DREAM" in h2.upper()
    return has_fb1 == has_fb2 and has_dr1 == has_dr2
