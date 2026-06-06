"""LLM router — model-to-task mapping and client factory for the DeepSeek API.

Uses LangChain's ChatOpenAI as a compatibility layer.  All calls carry an
httpx.Timeout to prevent hung requests in the pipeline.
"""

from __future__ import annotations

import logging
import os

import httpx
from langchain_openai import ChatOpenAI

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DeepSeek API configuration
# ---------------------------------------------------------------------------

DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"

# ---------------------------------------------------------------------------
# Model routing table — maps pipeline stage → DeepSeek model name
# ---------------------------------------------------------------------------

MODEL_ROUTING: dict[str, str] = {
    "global_extraction": "deepseek-v4-pro",
    "scene_conversion": "deepseek-v4-flash",
    "consistency_check": "deepseek-v4-pro",
    "chapter_split": "deepseek-v4-flash",
    "ai_chat": "deepseek-v4-flash",
}

# Per-stage max output tokens.  Prevents runaway generation and bounds
# cost.  Values are conservative — typical output is 50-70% of these caps.
_MAX_TOKENS: dict[str, int] = {
    "chapter_split":      2000,   # short JSON array of chapter titles
    "global_extraction":  6000,   # KG nodes + edges for a full novel
    "scene_conversion":   8000,   # scene list for one chapter
    "consistency_check":  4000,   # same-size output as input batch
    "ai_chat":            2000,   # conversational reply
}

# ---------------------------------------------------------------------------
# Timeout configuration
# ---------------------------------------------------------------------------

_REQUEST_TIMEOUT = httpx.Timeout(
    connect=10.0,
    read=180.0,   # increased from 120s — Pro model consistency check can
                   # take longer with larger inputs
    write=10.0,
    pool=5.0,
)


# ---------------------------------------------------------------------------
# Client factory
# ---------------------------------------------------------------------------


def get_llm(stage: str, temperature: float = 0.3, json_mode: bool = False) -> ChatOpenAI:
    """Return a LangChain ChatOpenAI instance routed to the correct DeepSeek model.

    Args:
        stage: One of the keys in MODEL_ROUTING.
        temperature: Sampling temperature (0.0–1.0).
        json_mode: If True, set ``response_format`` to ``{"type": "json_object"}``
            (DeepSeek native JSON mode, NOT OpenAI json_schema).  The prompt
            MUST contain the word "json" and describe the expected structure.

    Returns:
        A configured ChatOpenAI instance pointed at the DeepSeek API.

    Raises:
        ValueError: If *stage* is not found in MODEL_ROUTING.
    """
    model_name = MODEL_ROUTING.get(stage)
    if model_name is None:
        raise ValueError(
            f"Unknown pipeline stage '{stage}'. Valid stages: {list(MODEL_ROUTING)}"
        )

    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        logger.warning("DEEPSEEK_API_KEY is not set — LLM calls will fail.")
        api_key = "not-set"  # placeholder so the client can be constructed

    max_tokens = _MAX_TOKENS.get(stage)
    kwargs: dict = dict(
        model=model_name,
        base_url=DEEPSEEK_BASE_URL,
        api_key=api_key,
        temperature=temperature,
        timeout=_REQUEST_TIMEOUT,
        max_retries=2,
    )
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    if json_mode:
        kwargs["model_kwargs"] = {"response_format": {"type": "json_object"}}

    llm = ChatOpenAI(**kwargs)
    logger.debug("Created LLM client for stage=%s → model=%s json_mode=%s max_tokens=%s",
                 stage, model_name, json_mode, max_tokens)
    return llm
