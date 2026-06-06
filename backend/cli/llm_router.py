"""LLM router — model-to-task mapping and client factory for the DeepSeek API.

Uses LangChain's ChatOpenAI as a compatibility layer.  All calls carry an
httpx.Timeout to prevent hung requests in the pipeline.

Context-window and output-token limits are auto-detected from the
model name and can be overridden via environment variables::

    LLM_CONTEXT_WINDOW=128000      # manual override (tokens)
    LLM_MAX_OUTPUT_TOKENS=8192     # manual override (tokens)
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
    "chapter_summary": "deepseek-v4-flash",
    "ai_chat": "deepseek-v4-flash",
}

# Per-stage max output tokens.  These are soft caps — the actual max_tokens
# passed to the API is min(per_stage_cap, model_max_output).
_MAX_TOKENS: dict[str, int] = {
    "chapter_split":      2000,   # short JSON array of chapter titles
    "chapter_summary":     300,   # 100-200 char objective summary
    "global_extraction":  6000,   # KG nodes + edges for a full novel
    "scene_conversion":   8000,   # scene list for one chapter
    "consistency_check":  4000,   # same-size output as input batch
    "ai_chat":            2000,   # conversational reply
}

# ---------------------------------------------------------------------------
# Per-model context / output limits
# ---------------------------------------------------------------------------

_MODEL_LIMITS: dict[str, dict[str, int]] = {
    "deepseek-v4-pro":   {"context": 1_000_000, "max_output": 32_768},
    "deepseek-v4-flash": {"context": 1_000_000, "max_output": 32_768},
}

# CJK characters-per-token ≈ 0.6–0.8.  We use 0.6 as a conservative estimate
# to ensure even dense CJK text stays within the token budget.
_CJK_CHARS_PER_TOKEN = 0.6

# Fraction of context window to use for input text (leaving room for
# system prompt, format instructions, and output margin).
_CONTEXT_USAGE_RATIO = 0.60

# ---------------------------------------------------------------------------
# Timeout configuration
# ---------------------------------------------------------------------------

_REQUEST_TIMEOUT = httpx.Timeout(
    connect=10.0,
    read=180.0,
    write=10.0,
    pool=5.0,
)


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def get_llm_context_window(stage: str | None = None) -> int:
    """Return the effective context window size in *tokens*.

    Resolution order:
    1. ``LLM_CONTEXT_WINDOW`` env var (manual override).
    2. Per-model limit (keyed by the model name for *stage*).
    3. ``_MODEL_LIMITS`` default for the stage's model.
    """
    env_override = os.getenv("LLM_CONTEXT_WINDOW")
    if env_override:
        try:
            return int(env_override)
        except ValueError:
            logger.warning("LLM_CONTEXT_WINDOW=%r is not an integer — ignoring.", env_override)

    model_name = MODEL_ROUTING.get(stage or "ai_chat", "deepseek-v4-flash")
    limits = _MODEL_LIMITS.get(model_name, {})
    return limits.get("context", 128_000)  # safe fallback


def get_output_limit(stage: str | None = None) -> int:
    """Return the effective max output tokens.

    Resolution order:
    1. ``LLM_MAX_OUTPUT_TOKENS`` env var (manual override).
    2. Per-model limit.
    3. Per-stage soft cap from ``_MAX_TOKENS``.
    4. Safe default (4096).
    """
    env_override = os.getenv("LLM_MAX_OUTPUT_TOKENS")
    if env_override:
        try:
            return int(env_override)
        except ValueError:
            logger.warning("LLM_MAX_OUTPUT_TOKENS=%r is not an integer — ignoring.", env_override)

    model_name = MODEL_ROUTING.get(stage or "ai_chat", "deepseek-v4-flash")
    model_limit = _MODEL_LIMITS.get(model_name, {}).get("max_output", 8192)
    stage_cap = _MAX_TOKENS.get(stage or "", 4096)
    return min(model_limit, stage_cap)


def context_chars(stage: str) -> int:
    """Return the safe input-character budget for *stage*.

    This is the recommended maximum character count for the primary text
    block sent to the LLM.  It already accounts for CJK encoding density
    and prompt overhead.
    """
    return int(get_llm_context_window(stage) * _CJK_CHARS_PER_TOKEN * _CONTEXT_USAGE_RATIO)


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

    max_tokens = get_output_limit(stage)
    kwargs: dict = dict(
        model=model_name,
        base_url=DEEPSEEK_BASE_URL,
        api_key=api_key,
        temperature=temperature,
        timeout=_REQUEST_TIMEOUT,
        max_retries=2,
        max_tokens=max_tokens,
    )
    if json_mode:
        kwargs["model_kwargs"] = {"response_format": {"type": "json_object"}}

    llm = ChatOpenAI(**kwargs)
    ctx = get_llm_context_window(stage)
    logger.debug(
        "Created LLM client for stage=%s → model=%s json_mode=%s "
        "max_tokens=%s context_window=%s",
        stage, model_name, json_mode, max_tokens, ctx,
    )
    return llm
