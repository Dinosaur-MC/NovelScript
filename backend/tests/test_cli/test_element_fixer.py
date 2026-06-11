"""Tests for cli.element_fixer — internal monologue reclassification,
embedded character split, null source_ref flagging.

Updated for Schema 2.1.0 element types (DialogueBlock, ActionElement).
"""

from __future__ import annotations

import pytest

from cli.element_fixer import (
    fix_element_types,
    split_embedded_character,
    flag_missing_source_refs,
    _looks_like_character_name,
)
from cli.models import Element, SourceRef


def _action(content: str) -> Element:
    return Element(type="action", content=content)


def _dialogue(content: str, ref: SourceRef | None = None) -> Element:
    return Element(type="dialogue", content=content, source_ref=ref)


def _elem(typ: str, content: str, ref: SourceRef | None = None) -> Element:
    return Element(type=typ, content=content, source_ref=ref)


class TestFixElementTypes:
    """Internal monologue and self-talk reclassification.
    Now creates DialogueBlock objects with type="dialogue_block".
    """

    # ── Internal monologue patterns ────────────────────────────────────

    def test_internal_monologue_with_speaker(self) -> None:
        elements = [_action("李浮尘内心：关雪和他解除婚约，他并不吃惊")]
        result = fix_element_types(elements)
        assert result[0].type == "dialogue_block"
        assert "V.O." in getattr(result[0], "character_extension", "") or "V.O." in getattr(result[0], "dialogue", "")

    def test_internal_monologue_xinxiang(self) -> None:
        elements = [_action("李浮尘心想：为什么还是这样")]
        result = fix_element_types(elements)
        assert result[0].type == "dialogue_block"

    def test_internal_monologue_ancun(self) -> None:
        elements = [_action("老者暗忖：此子不凡")]
        result = fix_element_types(elements)
        assert result[0].type == "dialogue_block"

    def test_internal_monologue_xindao(self) -> None:
        elements = [_action("心道：这该如何是好")]
        result = fix_element_types(elements)
        assert result[0].type == "dialogue_block"

    def test_internal_monologue_no_speaker(self) -> None:
        elements = [_action("内心：不知道灰色雾气变成灰色光球，对我有没有好处")]
        result = fix_element_types(elements)
        assert result[0].type == "dialogue_block"

    def test_internal_monologue_anma(self) -> None:
        elements = [_action("暗骂：真是岂有此理")]
        result = fix_element_types(elements)
        assert result[0].type == "dialogue_block"

    def test_internal_monologue_with_parens(self) -> None:
        elements = [_action("李浮尘心里（暗暗）：这不对啊")]
        result = fix_element_types(elements)
        assert result[0].type == "dialogue_block"

    # ── Self-talk indicators ───────────────────────────────────────────

    def test_self_talk_nanNanDao(self) -> None:
        elements = [_action("李浮尘喃喃道：这就是人情冷暖吗")]
        result = fix_element_types(elements)
        assert result[0].type == "dialogue_block"

    def test_self_talk_diguDao(self) -> None:
        elements = [_action("老者嘀咕道：这天气真热")]
        result = fix_element_types(elements)
        assert result[0].type == "dialogue_block"

    # ── Non-matching cases (should stay as action) ─────────────────────

    def test_normal_action_passes_through(self) -> None:
        elements = [_action("张三大步走进大殿")]
        result = fix_element_types(elements)
        assert result[0].type == "action"

    def test_narrative_action_passes_through(self) -> None:
        elements = [_action("殿外乌云压顶，雷声隐隐")]
        result = fix_element_types(elements)
        assert result[0].type == "action"

    def test_dialogue_not_affected(self) -> None:
        elements = [_dialogue("臣有本启奏！")]
        result = fix_element_types(elements)
        assert result[0].type == "dialogue"

    def test_character_not_affected(self) -> None:
        elements = [_elem("character", "张三")]
        result = fix_element_types(elements)
        assert result[0].type == "character"


class TestSplitEmbeddedCharacter:
    """Splitting dialogue with embedded character names.
    Now modifies DialogueBlock in-place rather than splitting into 3 elements.
    """

    def test_split_name_with_parenthetical(self) -> None:
        elements = [_dialogue("二喜(大喊)：苦根！")]
        result = split_embedded_character(elements)
        assert len(result) == 1  # modified in-place
        assert result[0].type in ("dialogue", "dialogue_block")
        assert getattr(result[0], "dialogue", "") == "苦根！"

    def test_split_name_with_colon(self) -> None:
        elements = [_dialogue("福贵：今天有庆二喜耕一亩")]
        result = split_embedded_character(elements)
        assert result[0].type in ("dialogue", "dialogue_block")

    def test_split_with_chinese_colon(self) -> None:
        elements = [_dialogue("李云河：李浮尘，再练十年你也不是我对手")]
        result = split_embedded_character(elements)
        assert result[0].type in ("dialogue", "dialogue_block")

    def test_no_split_for_sentence_opener(self) -> None:
        elements = [_dialogue("然后他走进了大殿")]
        result = split_embedded_character(elements)
        assert len(result) == 1
        assert result[0].type == "dialogue"

    def test_no_split_for_long_content(self) -> None:
        elements = [_dialogue("这是一个很长很长很长的句子开始部分" + "x" * 50)]
        result = split_embedded_character(elements)
        assert len(result) == 1

    def test_preserves_source_ref(self) -> None:
        ref = SourceRef(chapter_id="ch_00", offset=[0, 10])
        elements = [_dialogue("张三：你好", ref=ref)]
        result = split_embedded_character(elements)
        assert result[0].source_ref is ref

    def test_mixed_elements(self) -> None:
        elements = [
            _action("张三走进来"),
            _dialogue("张三：大家好"),
            _action("众人鼓掌"),
        ]
        result = split_embedded_character(elements)
        assert result[0].type == "action"
        assert result[1].type in ("dialogue", "dialogue_block")
        assert result[2].type == "action"


class TestLooksLikeCharacterName:
    """Heuristic character name detection."""

    def test_two_char_name(self) -> None:
        assert _looks_like_character_name("张三") is True

    def test_three_char_name(self) -> None:
        assert _looks_like_character_name("李浮尘") is True

    def test_four_char_name(self) -> None:
        assert _looks_like_character_name("欧阳明日") is True

    def test_single_char_not_name(self) -> None:
        assert _looks_like_character_name("我") is False

    def test_too_long_not_name(self) -> None:
        assert _looks_like_character_name("这是一个很长的句子") is False

    def test_common_opener_not_name(self) -> None:
        assert _looks_like_character_name("然后") is False
        assert _looks_like_character_name("但是") is False
        assert _looks_like_character_name("所以") is False

    def test_non_chinese_not_name(self) -> None:
        assert _looks_like_character_name("John") is False


class TestFlagMissingSourceRefs:
    """Null source_ref detection."""

    def test_no_missing_refs(self) -> None:
        ref = SourceRef(chapter_id="ch_00", offset=[0, 4])
        elements = [
            _elem("action", "test", ref=ref),
            _elem("dialogue", "hello", ref=ref),
        ]
        flagged = flag_missing_source_refs(elements)
        assert len(flagged) == 0

    def test_flags_missing_refs(self) -> None:
        ref = SourceRef(chapter_id="ch_00", offset=[0, 4])
        elements = [
            _elem("action", "test", ref=ref),
            _elem("dialogue", "hello"),  # no ref
        ]
        flagged = flag_missing_source_refs(elements)
        assert len(flagged) == 1
        assert flagged[0]["type"] == "dialogue"
        assert flagged[0]["severity"] == "error"

    def test_action_missing_ref_is_warning(self) -> None:
        elements = [_elem("action", "test")]  # no ref
        flagged = flag_missing_source_refs(elements)
        assert flagged[0]["severity"] == "warning"
