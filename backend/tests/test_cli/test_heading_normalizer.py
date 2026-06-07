"""Tests for cli.heading_normalizer — Chinese→English prefix, flashback markers,
time-of-day normalisation, edge cases.
"""

from __future__ import annotations

import pytest

from cli.heading_normalizer import normalize_heading


class TestNormalizeHeading:
    """Core heading normalisation tests."""

    # ── Chinese → English prefix ──────────────────────────────────────

    def test_chinese_interior_prefix(self) -> None:
        assert normalize_heading("内景 练武场 - 白天") == "INT. 练武场 - DAY"

    def test_chinese_exterior_prefix(self) -> None:
        assert normalize_heading("外景 河边 - 夜晚") == "EXT. 河边 - NIGHT"

    def test_chinese_ie_prefix(self) -> None:
        assert normalize_heading("内外景 车厢 - 午后") == "INT./EXT. 车厢 - AFTERNOON"

    # ── Chinese → English time-of-day ──────────────────────────────────

    @pytest.mark.parametrize("chinese_time, english_time", [
        ("白天", "DAY"),
        ("日", "DAY"),
        ("夜晚", "NIGHT"),
        ("夜", "NIGHT"),
        ("深夜", "NIGHT"),
        ("傍晚", "DUSK"),
        ("黄昏", "DUSK"),
        ("午后", "AFTERNOON"),
        ("下午", "AFTERNOON"),
        ("清晨", "DAWN"),
        ("早晨", "MORNING"),
        ("上午", "MORNING"),
        ("几天后", "LATER"),
        ("黎明", "DAWN"),
    ])
    def test_time_normalisation(self, chinese_time: str, english_time: str) -> None:
        result = normalize_heading(f"内景 某地 - {chinese_time}")
        assert result == f"INT. 某地 - {english_time}"

    # ── Missing prefix (heuristic detection) ───────────────────────────

    def test_missing_prefix_heuristic_interior(self) -> None:
        result = normalize_heading("卧室 - 白天")
        assert result.startswith("INT. ")

    def test_missing_prefix_heuristic_exterior(self) -> None:
        result = normalize_heading("河边 - 午后")
        assert result.startswith("EXT. ")

    def test_missing_prefix_heuristic_hall(self) -> None:
        result = normalize_heading("大厅 - 日")
        assert result.startswith("INT. ")

    def test_missing_prefix_heuristic_shop(self) -> None:
        result = normalize_heading("店铺 - 白天")
        assert result.startswith("INT. ")

    # ── Flashback markers ──────────────────────────────────────────────

    def test_flashback_prefix_chinese(self) -> None:
        result = normalize_heading("闪回 - 徐家田地 - 傍晚")
        assert "FLASHBACK" in result
        assert "徐家田地" in result
        assert "DUSK" in result

    def test_flashback_prefix_no_dash(self) -> None:
        result = normalize_heading("闪回 青楼 - 夜")
        assert "FLASHBACK" in result

    def test_flashback_in_parens(self) -> None:
        result = normalize_heading("内景 房间 - 夜（闪回）")
        assert "(FLASHBACK)" in result
        assert "INT." in result

    def test_flashback_chinese_parens(self) -> None:
        result = normalize_heading("外景 战场 - 白天(闪回)")
        assert "(FLASHBACK)" in result
        assert "EXT." in result

    def test_memory_prefix(self) -> None:
        result = normalize_heading("回忆 - 童年小屋 - 白天")
        assert "FLASHBACK" in result

    # ── Dream markers ──────────────────────────────────────────────────

    def test_dream_marker(self) -> None:
        result = normalize_heading("内景 脑海 - 夜（梦）")
        assert "DREAM" in result

    # ── Already-standard headings pass through ─────────────────────────

    def test_already_standard_heading(self) -> None:
        result = normalize_heading("EXT. BEACH - DAY")
        assert result == "EXT. BEACH - DAY"

    def test_already_standard_with_flashback(self) -> None:
        result = normalize_heading("INT. ROOM - NIGHT (FLASHBACK)")
        assert result == "INT. ROOM - NIGHT (FLASHBACK)"

    # ── Edge cases ─────────────────────────────────────────────────────

    def test_empty_heading(self) -> None:
        result = normalize_heading("")
        # Should return something reasonable, not crash
        assert "EXT." in result or "INT." in result or "DAY" in result

    def test_multi_location_slash(self) -> None:
        result = normalize_heading("外景 田里/茅屋 - 白天")
        assert "EXT." in result
        assert "田里 / 茅屋" in result or "田里/茅屋" in result

    def test_relative_time(self) -> None:
        result = normalize_heading("外景 李家各处 - 几天后")
        assert "LATER" in result
        assert "EXT." in result

    def test_dream_with_location(self) -> None:
        result = normalize_heading("内景 李浮尘的脑海 - 夜（梦）")
        assert "DREAM" in result
        assert "NIGHT" in result or "夜" not in result

    def test_strip_trailing_punctuation(self) -> None:
        result = normalize_heading("外景 练武场。 - 白天")
        assert "练武场" in result
        assert "。" not in result
