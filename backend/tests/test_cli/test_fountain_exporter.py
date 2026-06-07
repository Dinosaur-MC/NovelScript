"""Tests for cli.fountain_exporter — Fountain 1.1 format output.

Verified against https://fountain.io/syntax rules.
"""

from __future__ import annotations

import pytest

from cli.fountain_exporter import to_fountain
from cli.models import (
    Character,
    Element,
    KnowledgeGraph,
    Scene,
    Script,
)


@pytest.fixture
def sample_script() -> Script:
    """A minimal script with a proper Character→Dialogue→Parenthetical→Dialogue block."""
    return Script(
        meta={
            "source_file": "Test Novel",
            "chapter_count": 2,
            "scene_count": 1,
        },
        summary="A test.",
        characters=[
            Character(id="n_01", name="张三", aliases=[], properties={}),
        ],
        scenes=[
            Scene(
                scene_id="s_0001",
                heading="EXT. TRAINING GROUND - DAY",
                location="Training Ground",
                time_of_day="DAY",
                elements=[
                    Element(type="action", content="Zhang San draws his sword."),
                    Element(type="character", content="Zhang San"),
                    Element(type="dialogue", content="I am ready."),
                    Element(type="parenthetical", content="angry"),
                    Element(type="dialogue", content="Fight me!"),
                    Element(type="action", content="He charges forward."),
                ],
                characters_present=["n_01"],
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
        """Fountain spec: character names are UPPERCASE, no padding needed."""
        output = to_fountain(sample_script)
        lines = output.split("\n")
        # Find the character line and verify no leading spaces
        char_line = [l for l in lines if "ZHANG SAN" in l][0]
        assert not char_line.startswith(" ")  # no leading spaces

    def test_dialogue_immediately_follows_character(self, sample_script: Script) -> None:
        """Fountain spec: Dialogue is any text following a Character element
        with NO blank line between them."""
        output = to_fountain(sample_script)
        lines = output.split("\n")
        # Find index of character line
        char_idx = lines.index([l for l in lines if "ZHANG SAN" in l][0])
        # Next line must be dialogue (not blank)
        assert lines[char_idx + 1] == "I am ready."

    def test_parenthetical_immediately_follows_dialogue(self, sample_script: Script) -> None:
        """Fountain spec: Parentheticals follow Character or Dialogue, no blank."""
        output = to_fountain(sample_script)
        lines = output.split("\n")
        dialogue_idx = lines.index("I am ready.")
        assert lines[dialogue_idx + 1] == "(angry)"

    def test_blank_line_before_character_cue(self, sample_script: Script) -> None:
        """Fountain spec: Character element has one empty line before it."""
        output = to_fountain(sample_script)
        lines = output.split("\n")
        char_idx = lines.index([l for l in lines if "ZHANG SAN" in l][0])
        assert lines[char_idx - 1] == ""  # blank line before

    def test_blank_line_after_dialogue_block(self, sample_script: Script) -> None:
        """After the dialogue block ends, there should be a blank line
        before the next action element."""
        output = to_fountain(sample_script)
        lines = output.split("\n")
        # "Fight me!" is last dialogue, then blank line, then "He charges forward."
        last_dialogue_idx = lines.index("Fight me!")
        assert lines[last_dialogue_idx + 1] == ""  # blank line after block
        assert lines[last_dialogue_idx + 2] == "He charges forward."

    def test_scene_separator(self, sample_script: Script) -> None:
        output = to_fountain(sample_script)
        assert "===" in output

    def test_empty_script(self) -> None:
        script = Script()
        output = to_fountain(script)
        assert len(output) > 0  # Should still have title page
        assert "===" in output

    def test_multiple_scenes(self) -> None:
        script = Script(
            scenes=[
                Scene(scene_id="s_0001", heading="EXT. A - DAY", location="A",
                      time_of_day="DAY", elements=[], characters_present=[]),
                Scene(scene_id="s_0002", heading="INT. B - NIGHT", location="B",
                      time_of_day="NIGHT", elements=[], characters_present=[]),
            ],
            knowledge_graph=KnowledgeGraph(),
        )
        output = to_fountain(script)
        assert "EXT. A - DAY" in output
        assert "INT. B - NIGHT" in output
        assert output.count("===") >= 3  # title sep + 2 scene seps

    def test_transition_element(self) -> None:
        script = Script(
            scenes=[
                Scene(scene_id="s_0001", heading="EXT. A - DAY", location="A",
                      time_of_day="DAY",
                      elements=[
                          Element(type="action", content="He walks away."),
                          Element(type="transition", content="CUT TO:"),
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
                Scene(scene_id="s_0001", heading="EXT. A - DAY", location="A",
                      time_of_day="DAY",
                      elements=[
                          Element(type="action", content="He sings."),
                          Element(type="lyric", content="La la la"),
                      ],
                      characters_present=[]),
            ],
            knowledge_graph=KnowledgeGraph(),
        )
        output = to_fountain(script)
        assert "~ La la la" in output

    def test_character_extension_via_parenthetical(self) -> None:
        """Character name with parenthetical on first dialogue line."""
        script = Script(
            scenes=[
                Scene(scene_id="s_0001", heading="EXT. A - DAY", location="A",
                      time_of_day="DAY",
                      elements=[
                          Element(type="character", content="JOHN"),
                          Element(type="parenthetical", content="V.O."),
                          Element(type="dialogue", content="I remember it well."),
                          Element(type="action", content="He sits."),
                      ],
                      characters_present=[]),
            ],
            knowledge_graph=KnowledgeGraph(),
        )
        output = to_fountain(script)
        # Check the dialogue block has no blank lines within it
        lines = output.split("\n")
        # Character → parenthetical → dialogue must be contiguous
        char_idx = lines.index("JOHN")
        assert lines[char_idx + 1] == "(V.O.)"
        assert lines[char_idx + 2] == "I remember it well."
        assert lines[char_idx + 3] == ""  # blank after block

    def test_standalone_action_no_extra_blanks(self) -> None:
        """Regular action should not create double blank lines."""
        script = Script(
            scenes=[
                Scene(scene_id="s_0001", heading="EXT. A - DAY", location="A",
                      time_of_day="DAY",
                      elements=[
                          Element(type="action", content="Line one."),
                          Element(type="action", content="Line two."),
                      ],
                      characters_present=[]),
            ],
            knowledge_graph=KnowledgeGraph(),
        )
        output = to_fountain(script)
        # Each action element followed by blank line = single blank separators
        assert "\n\n\n" not in output  # no triple blanks
