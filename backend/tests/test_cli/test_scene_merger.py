"""Tests for cli.scene_merger — micro-scene merging, time compatibility, edge cases."""

from __future__ import annotations

import pytest

from cli.models import Element, Scene
from cli.scene_merger import merge_tiny_scenes, _time_compatible, _special_compatible


def _scene(sid: str, location: str, time: str, elements: list[Element],
           heading: str = "") -> Scene:
    return Scene(
        scene_id=sid,
        heading=heading or f"EXT. {location} - {time}",
        location=location,
        time_of_day=time,
        elements=elements,
        characters_present=["n_01"],
    )


def _elem(typ: str = "action", content: str = "x") -> Element:
    return Element(type=typ, content=content)


class TestMergeTinyScenes:
    """Core merge logic."""

    def test_empty_scenes(self) -> None:
        assert merge_tiny_scenes([]) == []

    def test_single_scene(self) -> None:
        s = _scene("s_0001", "大殿", "DAY", [_elem(), _elem()])
        result = merge_tiny_scenes([s])
        assert len(result) == 1

    def test_merge_two_same_location(self) -> None:
        s1 = _scene("s_0001", "大殿", "DAY", [_elem(), _elem(), _elem()])
        s2 = _scene("s_0002", "大殿", "DAY", [_elem()])  # only 1 element → merge
        result = merge_tiny_scenes([s1, s2])
        assert len(result) == 1
        assert len(result[0].elements) == 4  # merged

    def test_no_merge_different_location(self) -> None:
        s1 = _scene("s_0001", "大殿", "DAY", [_elem(), _elem(), _elem()])
        s2 = _scene("s_0002", "花园", "DAY", [_elem()])
        result = merge_tiny_scenes([s1, s2])
        assert len(result) == 2

    def test_no_merge_min_elements_met(self) -> None:
        s1 = _scene("s_0001", "大殿", "DAY", [_elem(), _elem(), _elem()])
        s2 = _scene("s_0002", "大殿", "DAY", [_elem(), _elem()])  # 2 elements → no merge
        result = merge_tiny_scenes([s1, s2], min_elements=2)
        assert len(result) == 2

    def test_merge_preserves_first_heading(self) -> None:
        s1 = _scene("s_0001", "大殿", "DAY", [_elem(), _elem()],
                     heading="INT. 大殿 - DAY")
        s2 = _scene("s_0002", "大殿", "DAY", [_elem()],
                     heading="INT. 大殿 - DAY (LATER)")
        result = merge_tiny_scenes([s1, s2])
        assert result[0].heading == "INT. 大殿 - DAY"  # keeps first

    def test_merge_union_characters(self) -> None:
        s1 = _scene("s_0001", "大殿", "DAY", [_elem(), _elem()])
        s1.characters_present = ["n_01", "n_02"]
        s2 = _scene("s_0002", "大殿", "DAY", [_elem()])
        s2.characters_present = ["n_03"]
        result = merge_tiny_scenes([s1, s2])
        assert set(result[0].characters_present) == {"n_01", "n_02", "n_03"}

    def test_chain_merge(self) -> None:
        """Three scenes at same location — first big, then two tiny."""
        s1 = _scene("s_0001", "大殿", "DAY", [_elem(), _elem(), _elem()])
        s2 = _scene("s_0002", "大殿", "DAY", [_elem()])
        s3 = _scene("s_0003", "大殿", "DAY", [_elem()])
        result = merge_tiny_scenes([s1, s2, s3])
        assert len(result) == 1
        assert len(result[0].elements) == 5

    def test_no_merge_when_second_has_enough(self) -> None:
        s1 = _scene("s_0001", "大殿", "DAY", [_elem(), _elem(), _elem()])
        s2 = _scene("s_0002", "大殿", "DAY", [_elem(), _elem()])  # 2 elements
        s3 = _scene("s_0003", "大殿", "DAY", [_elem()])  # 1 element, but after s2
        result = merge_tiny_scenes([s1, s2, s3], min_elements=2)
        # s3 merges into s2
        assert len(result) == 2
        assert len(result[1].elements) == 3

    def test_same_location_only_false(self) -> None:
        s1 = _scene("s_0001", "大殿", "DAY", [_elem(), _elem(), _elem()])
        s2 = _scene("s_0002", "花园", "DAY", [_elem()])
        result = merge_tiny_scenes([s1, s2], same_location_only=False)
        assert len(result) == 1  # merged despite different location


class TestTimeCompatible:
    """Time-of-day compatibility for merging."""

    def test_same_time(self) -> None:
        assert _time_compatible("DAY", "DAY") is True

    def test_compatible_pair(self) -> None:
        assert _time_compatible("DAY", "MORNING") is True

    def test_compatible_reverse(self) -> None:
        assert _time_compatible("MORNING", "DAY") is True

    def test_incompatible(self) -> None:
        assert _time_compatible("DAY", "NIGHT") is False

    def test_dusk_night_compatible(self) -> None:
        assert _time_compatible("DUSK", "NIGHT") is True

    def test_case_insensitive(self) -> None:
        assert _time_compatible("day", "DAY") is True


class TestSpecialCompatible:
    """Flashback/dream compatibility."""

    def test_both_normal(self) -> None:
        assert _special_compatible("EXT. A - DAY", "EXT. B - DAY") is True

    def test_both_flashback(self) -> None:
        assert _special_compatible(
            "EXT. A - DAY (FLASHBACK)",
            "EXT. B - NIGHT (FLASHBACK)",
        ) is True

    def test_flashback_vs_normal(self) -> None:
        assert _special_compatible(
            "EXT. A - DAY (FLASHBACK)",
            "EXT. B - DAY",
        ) is False

    def test_dream_vs_flashback(self) -> None:
        assert _special_compatible(
            "INT. A - NIGHT (DREAM)",
            "EXT. B - DAY (FLASHBACK)",
        ) is False
