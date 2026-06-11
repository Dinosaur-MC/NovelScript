"""Tests for cli.heading_normalizer — Chinese→English prefix, flashback markers,
time-of-day normalisation, edge cases.  Updated for Heading object return type.
"""

from __future__ import annotations

import pytest

from cli.heading_normalizer import normalize_heading
from cli.models import IntExt, NarrativeMode, TimeOfDay


class TestNormalizeHeading:
    """Core heading normalisation tests — check .text and sub-fields."""

    # ── Chinese → English prefix ──────────────────────────────────────

    def test_chinese_interior_prefix(self) -> None:
        h = normalize_heading("内景 练武场 - 白天")
        assert h.text == "INT. 练武场 - DAY"
        assert h.int_ext == IntExt.INT
        assert h.location == "练武场"

    def test_chinese_exterior_prefix(self) -> None:
        h = normalize_heading("外景 河边 - 夜晚")
        assert h.text == "EXT. 河边 - NIGHT"
        assert h.int_ext == IntExt.EXT

    def test_chinese_ie_prefix(self) -> None:
        h = normalize_heading("内外景 车厢 - 午后")
        assert h.text == "INT./EXT. 车厢 - DAY"  # 午后 → DAY
        assert h.int_ext == IntExt.INT_EXT

    # ── Chinese → English time-of-day ──────────────────────────────────

    @pytest.mark.parametrize("chinese_time, english_time", [
        ("白天", "DAY"),
        ("日", "DAY"),
        ("夜晚", "NIGHT"),
        ("夜", "NIGHT"),
        ("深夜", "NIGHT"),
        ("傍晚", "DUSK"),
        ("黄昏", "DUSK"),
        ("午后", "DAY"),      # Schema has no AFTERNOON → DAY
        ("下午", "DAY"),
        ("清晨", "DAWN"),
        ("早晨", "DAWN"),     # Schema has no MORNING → DAWN
        ("上午", "DAY"),
        ("几天后", "LATER"),
        ("黎明", "DAWN"),
    ])
    def test_time_normalisation(self, chinese_time: str, english_time: str) -> None:
        h = normalize_heading(f"内景 某地 - {chinese_time}")
        assert h.text == f"INT. 某地 - {english_time}"
        assert h.time_of_day.value == english_time

    # ── Missing prefix (heuristic detection) ───────────────────────────

    def test_missing_prefix_heuristic_interior(self) -> None:
        h = normalize_heading("卧室 - 白天")
        assert h.text.startswith("INT. ")
        assert h.int_ext == IntExt.INT

    def test_missing_prefix_heuristic_exterior(self) -> None:
        h = normalize_heading("河边 - 午后")
        assert h.text.startswith("EXT. ")

    def test_missing_prefix_heuristic_hall(self) -> None:
        h = normalize_heading("大厅 - 日")
        assert h.text.startswith("INT. ")

    def test_missing_prefix_heuristic_shop(self) -> None:
        h = normalize_heading("店铺 - 白天")
        assert h.text.startswith("INT. ")

    # ── Flashback markers ──────────────────────────────────────────────

    def test_flashback_prefix_chinese(self) -> None:
        h = normalize_heading("闪回 - 徐家田地 - 傍晚")
        assert "徐家田地" in h.text
        assert "DUSK" in h.text
        assert h.narrative_mode == NarrativeMode.FLASHBACK

    def test_flashback_prefix_no_dash(self) -> None:
        h = normalize_heading("闪回 青楼 - 夜")
        assert h.narrative_mode == NarrativeMode.FLASHBACK

    def test_flashback_in_parens(self) -> None:
        h = normalize_heading("内景 房间 - 夜（闪回）")
        assert h.narrative_mode == NarrativeMode.FLASHBACK
        assert "INT." in h.text

    def test_flashback_chinese_parens(self) -> None:
        h = normalize_heading("外景 战场 - 白天(闪回)")
        assert h.narrative_mode == NarrativeMode.FLASHBACK
        assert "EXT." in h.text

    def test_memory_prefix(self) -> None:
        h = normalize_heading("回忆 - 童年小屋 - 白天")
        assert h.narrative_mode == NarrativeMode.FLASHBACK

    # ── Dream markers ──────────────────────────────────────────────────

    def test_dream_marker(self) -> None:
        h = normalize_heading("内景 脑海 - 夜（梦）")
        assert h.narrative_mode == NarrativeMode.DREAM

    # ── Already-standard headings pass through ─────────────────────────

    def test_already_standard_heading(self) -> None:
        h = normalize_heading("EXT. BEACH - DAY")
        assert h.text == "EXT. BEACH - DAY"
        assert h.int_ext == IntExt.EXT

    def test_already_standard_with_flashback(self) -> None:
        h = normalize_heading("INT. ROOM - NIGHT (FLASHBACK)")
        assert h.narrative_mode == NarrativeMode.FLASHBACK
        assert "NIGHT" in h.text

    # ── Edge cases ─────────────────────────────────────────────────────

    def test_empty_heading(self) -> None:
        h = normalize_heading("")
        assert len(h.text) > 0  # returns something reasonable

    def test_multi_location_slash(self) -> None:
        h = normalize_heading("外景 田里/茅屋 - 白天")
        assert "EXT." in h.text
        assert "田里" in h.text
        assert "茅屋" in h.text

    def test_relative_time(self) -> None:
        h = normalize_heading("外景 李家各处 - 几天后")
        assert h.time_of_day == TimeOfDay.LATER
        assert "EXT." in h.text

    def test_dream_with_location(self) -> None:
        h = normalize_heading("内景 李浮尘的脑海 - 夜（梦）")
        assert h.narrative_mode == NarrativeMode.DREAM
        assert "NIGHT" in h.text

    def test_strip_trailing_punctuation(self) -> None:
        h = normalize_heading("外景 练武场。 - 白天")
        assert "练武场" in h.text
        assert "。" not in h.text
        assert h.location == "练武场"
