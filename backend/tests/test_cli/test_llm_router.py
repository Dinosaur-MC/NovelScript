"""Tests for cli.llm_router — model routing, client factory, error handling."""

from __future__ import annotations

import os
from unittest.mock import patch

import httpx
import pytest
from langchain_openai import ChatOpenAI

from cli.llm_router import DEEPSEEK_BASE_URL, MODEL_ROUTING, get_llm


class TestModelRouting:
    """Routing table correctly maps stage → model name."""

    def test_pro_stages_route_to_pro(self) -> None:
        assert MODEL_ROUTING["global_extraction"] == "deepseek-v4-pro"
        assert MODEL_ROUTING["consistency_check"] == "deepseek-v4-pro"

    def test_flash_stages_route_to_flash(self) -> None:
        assert MODEL_ROUTING["scene_conversion"] == "deepseek-v4-flash"
        assert MODEL_ROUTING["chapter_split"] == "deepseek-v4-flash"

    def test_routing_table_has_all_required_stages(self) -> None:
        for stage in ("global_extraction", "scene_conversion",
                      "consistency_check", "chapter_split"):
            assert stage in MODEL_ROUTING, f"Missing stage: {stage}"


class TestGetLLM:
    """Client factory produces correct ChatOpenAI instances."""

    def test_returns_chat_openai_instance(self) -> None:
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}):
            llm = get_llm("scene_conversion")
            assert isinstance(llm, ChatOpenAI)

    def test_uses_correct_model_name(self) -> None:
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}):
            llm = get_llm("global_extraction")
            assert llm.model_name == "deepseek-v4-pro"

            llm2 = get_llm("chapter_split")
            assert llm2.model_name == "deepseek-v4-flash"

    def test_custom_temperature(self) -> None:
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}):
            llm = get_llm("scene_conversion", temperature=0.9)
            assert llm.temperature == 0.9

    def test_default_temperature_is_0_3(self) -> None:
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}):
            llm = get_llm("scene_conversion")
            assert llm.temperature == 0.3

    def test_unknown_stage_raises_value_error(self) -> None:
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}):
            with pytest.raises(ValueError, match="Unknown pipeline stage"):
                get_llm("nonexistent_stage")

    def test_missing_api_key_uses_placeholder(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            if "DEEPSEEK_API_KEY" in os.environ:
                del os.environ["DEEPSEEK_API_KEY"]
            llm = get_llm("scene_conversion")
            # Should not raise; uses "not-set" placeholder
            assert isinstance(llm, ChatOpenAI)

    def test_deepseek_base_url_is_correct(self) -> None:
        assert DEEPSEEK_BASE_URL == "https://api.deepseek.com/v1"

    def test_uses_httpx_timeout(self) -> None:
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}):
            llm = get_llm("scene_conversion")
            # ChatOpenAI stores timeout in request_timeout; check it exists
            assert hasattr(llm, "request_timeout")
            timeout_val = llm.request_timeout
            assert isinstance(timeout_val, (int, float)) or hasattr(timeout_val, "read")

    def test_max_retries_is_two(self) -> None:
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}):
            llm = get_llm("scene_conversion")
            assert llm.max_retries == 2

    def test_json_mode_disabled_by_default(self) -> None:
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}):
            llm = get_llm("scene_conversion")
            assert llm.model_kwargs is None or llm.model_kwargs == {}

    def test_json_mode_enabled_adds_response_format(self) -> None:
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}):
            llm = get_llm("scene_conversion", json_mode=True)
            assert llm.model_kwargs is not None
            assert llm.model_kwargs.get("response_format") == {"type": "json_object"}
