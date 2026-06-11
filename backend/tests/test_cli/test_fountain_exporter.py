"""Tests for cli.fountain_exporter — Fountain 1.1 format output.

Verified against https://fountain.io/syntax rules.
"""

from __future__ import annotations

import pytest

from cli.fountain_exporter import to_fountain
from cli.models import (
    ActionElement,
    Character,
    DialogueBlock,
    Heading,
    KnowledgeGraph,
    LyricElement,
    Scene,
    Script,
    TransitionElement,
)


@pytest.fixture
def sample_script() -> Script:
    """A minimal script with proper DialogueBlock elements."""
    return Script(
        title_page={"Title": "Test Novel"},
        summary="A test.",
        characters=[
            Character(id="char_01", name="张三", aliases=[], description=""),
        ],
        scenes=[
            Scene(
                scene_id="s_0001",
                heading=Heading(text="EXT. TRAINING GROUND - DAY", location="Training Ground", time_of_day="DAY"),
                elements=[
                    ActionElement(text="Zhang San draws his sword."),
                    DialogueBlock(character_name="Zhang San", dialogue="I am ready."),
                    DialogueBlock(character_name="", dialogue="Fight me!", parenthetical="(angry)"),
                    ActionElement(text="He charges forward."),
                ],
                characters_present=["char_01"],
            ),
        ],
        knowledge_graph=KnowledgeGraph(),
    )


class TestFountainExporter:
    """Core fountain export tests."""

    def test_output_is_non_empty(self, sample_script: Script) -> None:
        output = to_fountain(sample_script)
        assert len(output) > 0

    def test_title_page_elements(self, sample_script: Script) -> None:
        output = to_fountain(sample_script)
        assert "Title:" in output
        assert "Test Novel" in output
        assert "Credit:" in output
        assert "NovelScript" in output

    def test_scene_heading_present(self, sample_script: Script) -> None:
        output = to_fountain(sample_script)
        assert "EXT. TRAINING GROUND - DAY" in output

    def test_action_element_present(self, sample_script: Script) -> None:
        output = to_fountain(sample_script)
        assert "Zhang San draws his sword." in output
        assert "He charges forward." in output

    def test_character_name_uppercased(self, sample_script: Script) -> None:
        output = to_fountain(sample_script)
        assert "ZHANG SAN" in output

    def test_character_not_right_padded(self, sample_script: Script) -> None:
        output = to_fountain(sample_script)
        lines = output.split("\n")
        char_line = [l for l in lines if "ZHANG SAN" in l][0]
        assert not char_line.startswith(" ")

    def test_dialogue_immediately_follows_character(self, sample_script: Script) -> None:
        output = to_fountain(sample_script)
        lines = output.split("\n")
        char_idx = lines.index([l for l in lines if "ZHANG SAN" in l][0])
        assert lines[char_idx + 1] == "I am ready."

    def test_parenthetical_immediately_follows_dialogue(self, sample_script: Script) -> None:
        """Parenthetical (angry) is on the second DialogueBlock before 'Fight me!'."""
        output = to_fountain(sample_script)
        lines = output.split("\n")
        fight_idx = lines.index("Fight me!")
        assert lines[fight_idx - 1] == "(angry)"

    def test_blank_line_before_character_cue(self, sample_script: Script) -> None:
        output = to_fountain(sample_script)
        lines = output.split("\n")
        char_idx = lines.index([l for l in lines if "ZHANG SAN" in l][0])
        assert lines[char_idx - 1] == ""  # blank line before

    def test_blank_line_after_dialogue_block(self, sample_script: Script) -> None:
        output = to_fountain(sample_script)
        lines = output.split("\n")
        # "Fight me!" is last dialogue, then blank, then "He charges forward."
        last_dialogue_idx = lines.index("Fight me!")
        assert lines[last_dialogue_idx + 1] == ""
        assert lines[last_dialogue_idx + 2] == "He charges forward."

    def test_scene_separator(self, sample_script: Script) -> None:
        output = to_fountain(sample_script)
        assert "===" in output

    def test_empty_script(self) -> None:
        script = Script()
        output = to_fountain(script)
        assert len(output) > 0
        assert "===" in output

    def test_multiple_scenes(self) -> None:
        script = Script(
            scenes=[
                Scene(scene_id="s_0001", heading=Heading(text="EXT. A - DAY", location="A", time_of_day="DAY"),
                      elements=[], characters_present=[]),
                Scene(scene_id="s_0002", heading=Heading(text="INT. B - NIGHT", location="B", time_of_day="NIGHT"),
                      elements=[], characters_present=[]),
            ],
            knowledge_graph=KnowledgeGraph(),
        )
        output = to_fountain(script)
        assert "EXT. A - DAY" in output
        assert "INT. B - NIGHT" in output
        assert output.count("===") >= 3

    def test_transition_element(self) -> None:
        script = Script(
            scenes=[
                Scene(scene_id="s_0001", heading=Heading(text="EXT. A - DAY", location="A", time_of_day="DAY"),
                      elements=[
                          ActionElement(text="He walks away."),
                          TransitionElement(text="CUT TO:"),
                      ],
                      characters_present=[]),
            ],
            knowledge_graph=KnowledgeGraph(),
        )
        output = to_fountain(script)
        assert "CUT TO:" in output

    def test_lyric_element(self) -> None:
        script = Script(
            scenes=[
                Scene(scene_id="s_0001", heading=Heading(text="EXT. A - DAY", location="A", time_of_day="DAY"),
                      elements=[
                          ActionElement(text="He sings."),
                          LyricElement(text="La la la"),
                      ],
                      characters_present=[]),
            ],
            knowledge_graph=KnowledgeGraph(),
        )
        output = to_fountain(script)
        assert "~ La la la" in output

    def test_character_extension_via_parenthetical(self) -> None:
        """Character name with V.O. extension."""
        script = Script(
            scenes=[
                Scene(scene_id="s_0001", heading=Heading(text="EXT. A - DAY", location="A", time_of_day="DAY"),
                      elements=[
                          DialogueBlock(character_name="JOHN", character_extension="(V.O.)",
                                        dialogue="I remember it well."),
                          ActionElement(text="He sits."),
                      ],
                      characters_present=[]),
            ],
            knowledge_graph=KnowledgeGraph(),
        )
        output = to_fountain(script)
        lines = output.split("\n")
        char_idx = lines.index("JOHN (V.O.)")
        assert lines[char_idx + 1] == "I remember it well."
        assert lines[char_idx + 2] == ""

    def test_standalone_action_no_extra_blanks(self) -> None:
        script = Script(
            scenes=[
                Scene(scene_id="s_0001", heading=Heading(text="EXT. A - DAY", location="A", time_of_day="DAY"),
                      elements=[
                          ActionElement(text="Line one."),
                          ActionElement(text="Line two."),
                      ],
                      characters_present=[]),
            ],
            knowledge_graph=KnowledgeGraph(),
        )
        output = to_fountain(script)
        assert "\n\n\n" not in output
