"""LLM router — model-to-task mapping, client factory, retry logic, and usage tracking.

All LLM invocations are wrapped in ``invoke_with_retry()`` which provides
exponential backoff with jitter for transient failures (connection errors,
rate limits, timeouts, server errors).  Retry counts are per-stage
configurable via ``_RETRY_CONFIG`` and the ``LLM_MAX_RETRIES`` env var.

Uses LangChain's ChatOpenAI as a compatibility layer.  All calls carry an
httpx.Timeout to prevent hung requests in the pipeline.

Context-window and output-token limits are auto-detected from the
model name and can be overridden via environment variables::

    LLM_CONTEXT_WINDOW=128000      # manual override (tokens)
    LLM_MAX_OUTPUT_TOKENS=8192     # manual override (tokens)

Token usage is tracked per-model via a LangChain callback attached to
every ``ChatOpenAI`` instance created by ``get_llm()``.  Callers can
inspect accumulated usage with ``get_token_usage()`` and reset counters
between runs with ``reset_token_usage()``.
"""

from __future__ import annotations

import logging
import os
import random
import threading
import time
from dataclasses import dataclass, field
from typing import Any
import asyncio

import httpx
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult
from langchain_core.runnables import RunnableSerializable
from langchain_openai import ChatOpenAI
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    InternalServerError,
    RateLimitError,
)

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

# Per-stage retry configuration.  Each stage gets this many extra attempts
# (on top of the first try) before giving up.  Retries use exponential
# backoff with jitter.
_RETRY_CONFIG: dict[str, int] = {
    "chapter_split":      1,
    "chapter_summary":    1,
    "global_extraction":  2,
    "scene_conversion":   2,
    "consistency_check":  3,   # higher — runs near the end, losing it is costly
    "ai_chat":            1,
}

# Base delays for exponential backoff (seconds)
_RETRY_BASE_DELAY = 1.0
_RETRY_MAX_DELAY = 30.0
_RETRY_BACKOFF_FACTOR = 2.0

# ---------------------------------------------------------------------------
# Per-model context / output limits
# ---------------------------------------------------------------------------

_MODEL_LIMITS: dict[str, dict[str, int]] = {
    "deepseek-v4-pro":   {"context": 1_000_000, "max_output": 384_000},
    "deepseek-v4-flash": {"context": 1_000_000, "max_output": 384_000},
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
# Concurrency limiter — prevents flooding the LLM API with too many
# parallel calls (default: 20).  Override via ``LLM_MAX_CONCURRENCY`` env var.
#
# DeepSeek API limits (for reference):
#   deepseek-v4-pro   500
#   deepseek-v4-flash 2500
# ---------------------------------------------------------------------------

_llm_semaphore: asyncio.Semaphore | None = None

_DEFAULT_MAX_CONCURRENCY = 20


def get_llm_semaphore() -> asyncio.Semaphore:
    """Return a module-level :class:`asyncio.Semaphore` that gates concurrent
    LLM API calls.  Created lazily on first access so the env var is
    guaranteed to have been loaded by that point.
    """
    global _llm_semaphore
    if _llm_semaphore is None:
        max_cc = int(os.getenv("LLM_MAX_CONCURRENCY", _DEFAULT_MAX_CONCURRENCY))
        _llm_semaphore = asyncio.Semaphore(max_cc)
        logger.debug("LLM concurrency limit: %d", max_cc)
    return _llm_semaphore


# ---------------------------------------------------------------------------
# Token usage tracking — per-model accumulated counters + LangChain callback
# ---------------------------------------------------------------------------

@dataclass
class _UsageAccumulator:
    """Thread-safe per-model token counter."""

    model_name: str = ""
    prompt_tokens: int = 0
    prompt_cache_hit: int = 0
    prompt_cache_miss: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    call_count: int = 0


class _UsageTracker(BaseCallbackHandler):
    """LangChain callback that intercepts ``on_llm_end`` to capture token usage.

    Because multiple LLM calls can run concurrently (via ``asyncio.to_thread``),
    ``on_llm_end`` can fire from different OS threads.  We guard the shared
    accumulator dict with a ``threading.Lock``.
    """

    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self._acc: dict[str, _UsageAccumulator] = {}  # model_name → accumulator

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        model = self._extract_model(response)
        tokens = self._extract_tokens(response)
        logger.debug("UsageTracker.on_llm_end: model=%s tokens=%s", model, tokens)
        if model is None:
            return
        if tokens is None:
            return
        with self._lock:
            if model not in self._acc:
                self._acc[model] = _UsageAccumulator(model_name=model)
            acc = self._acc[model]
            acc.prompt_tokens += tokens.get("prompt_tokens", 0)
            acc.prompt_cache_hit += tokens.get("prompt_cache_hit_tokens", 0)
            acc.prompt_cache_miss += tokens.get("prompt_cache_miss_tokens", 0)
            acc.completion_tokens += tokens.get("completion_tokens", 0)
            acc.reasoning_tokens += tokens.get("reasoning_tokens", 0)
            acc.call_count += 1

    def get_accumulators(self) -> list[_UsageAccumulator]:
        with self._lock:
            return list(self._acc.values())

    def reset(self) -> None:
        with self._lock:
            self._acc.clear()

    @staticmethod
    def _extract_model(response: LLMResult) -> str | None:
        # response.llm_output is set by ChatOpenAI and contains model name
        llm_out = response.llm_output or {}
        model = llm_out.get("model_name")
        return model or None

    @staticmethod
    def _extract_tokens(response: LLMResult) -> dict[str, int] | None:
        """Extract token usage from the LLM response.

        ChatOpenAI stores the raw OpenAI response in
        ``LLMResult.llm_output["token_usage"]`` which mirrors the
        ``usage`` field documented at:
        https://api-docs.deepseek.com/zh-cn/api/create-chat-completion

        The dict contains:
          prompt_tokens, completion_tokens, total_tokens,
          prompt_cache_hit_tokens, prompt_cache_miss_tokens,
          completion_tokens_details: {reasoning_tokens}
        """
        llm_out = response.llm_output or {}
        usage = llm_out.get("token_usage", {})
        if not usage:
            # Fallback: try generations[0].message.usage_metadata
            try:
                gen_list = response.generations
                if gen_list and gen_list[0]:
                    msg = getattr(gen_list[0][0], "message", None)
                    if msg and msg.usage_metadata:
                        return {
                            "prompt_tokens": msg.usage_metadata.get("input_tokens", 0),
                            "completion_tokens": msg.usage_metadata.get("output_tokens", 0),
                            "total_tokens": msg.usage_metadata.get("total_tokens", 0),
                        }
            except (IndexError, AttributeError, TypeError):
                pass
            return None

        details = usage.get("completion_tokens_details", {}) or {}
        return {
            "prompt_tokens": int(usage.get("prompt_tokens", 0)),
            "completion_tokens": int(usage.get("completion_tokens", 0)),
            "total_tokens": int(usage.get("total_tokens", 0)),
            "prompt_cache_hit_tokens": int(usage.get("prompt_cache_hit_tokens", 0)),
            "prompt_cache_miss_tokens": int(usage.get("prompt_cache_miss_tokens", 0)),
            "reasoning_tokens": int(details.get("reasoning_tokens", 0)),
        }


# Module-level singleton tracker (attached to every ChatOpenAI via get_llm)
_usage_tracker = _UsageTracker()


def get_usage_tracker() -> _UsageTracker:
    """Return the global module-level :class:`_UsageTracker`."""
    return _usage_tracker


# ---------------------------------------------------------------------------
# Per-model pricing (DeepSeek, ¥ per million tokens)
# https://api-docs.deepseek.com/zh-cn/quick_start/pricing
# ---------------------------------------------------------------------------

_PRICING: dict[str, dict[str, float]] = {
    "deepseek-v4-pro": {
        "input_cache_hit":  0.025,   # ¥ / 1M tokens
        "input_cache_miss": 3.0,
        "output":           6.0,
    },
    "deepseek-v4-flash": {
        "input_cache_hit":  0.02,
        "input_cache_miss": 1.0,
        "output":           2.0,
    },
}

# Fallback pricing for unknown models (conservative: treat as Pro)
_DEFAULT_PRICING = _PRICING["deepseek-v4-pro"]


def compute_cost(
    model_name: str,
    prompt_cache_hit: int = 0,
    prompt_cache_miss: int = 0,
    completion_tokens: int = 0,
) -> float:
    """Compute the estimated cost in **元 (CNY)** for an LLM call.

    Args:
        model_name:         e.g. ``"deepseek-v4-flash"``.
        prompt_cache_hit:   Tokens that hit the context cache (discounted).
        prompt_cache_miss:  Tokens that did not hit the cache.
        completion_tokens:  Output tokens generated.

    Returns:
        Cost in 元 (CNY), never negative.
    """
    pricing = _PRICING.get(model_name, _DEFAULT_PRICING)
    cost = 0.0
    cost += prompt_cache_hit * pricing["input_cache_hit"] / 1_000_000
    cost += prompt_cache_miss * pricing["input_cache_miss"] / 1_000_000
    cost += completion_tokens * pricing["output"] / 1_000_000
    return cost


def reset_token_usage() -> None:
    """Clear accumulated token counters (call before starting a new pipeline run)."""
    _usage_tracker.reset()


def get_token_usage() -> dict[str, dict]:
    """Return accumulated per-model token usage with computed costs.

    Returns a dict suitable for ``meta.usage`` in the output Script,
    plus a human-readable ``meta.usage_summary`` string::

        {
          "deepseek-v4-pro": {
            "calls": 4,
            "prompt_tokens": 120000,
            "prompt_cache_hit": 0,
            "prompt_cache_miss": 120000,
            "completion_tokens": 8000,
            "reasoning_tokens": 0,
            "cost_yuan": 0.408
          },
          "deepseek-v4-flash": {...},
          "total_cost_yuan": 1.234
        }
    """
    result: dict[str, dict] = {}
    total_cost = 0.0
    for acc in _usage_tracker.get_accumulators():
        cost = compute_cost(
            acc.model_name,
            prompt_cache_hit=acc.prompt_cache_hit,
            prompt_cache_miss=acc.prompt_cache_miss,
            completion_tokens=acc.completion_tokens,
        )
        total_cost += cost
        result[acc.model_name] = {
            "calls": acc.call_count,
            "prompt_tokens": acc.prompt_tokens,
            "prompt_cache_hit": acc.prompt_cache_hit,
            "prompt_cache_miss": acc.prompt_cache_miss,
            "completion_tokens": acc.completion_tokens,
            "reasoning_tokens": acc.reasoning_tokens,
            "cost_yuan": round(cost, 6),
        }
    result["total_cost_yuan"] = round(total_cost, 6)
    return result


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
# Retry logic
# ---------------------------------------------------------------------------


def _get_retry_count(stage: str) -> int:
    """Return the max retry count for *stage*.

    Can be overridden globally via ``LLM_MAX_RETRIES`` env var.
    """
    env_override = os.getenv("LLM_MAX_RETRIES")
    if env_override:
        try:
            return int(env_override)
        except ValueError:
            logger.warning("LLM_MAX_RETRIES=%r is not an integer — ignoring.", env_override)
    return _RETRY_CONFIG.get(stage, 1)


def invoke_with_retry(
    chain: RunnableSerializable[Any, Any],
    inputs: dict[str, Any],
    stage: str,
) -> Any:
    """Invoke an LCEL *chain* with exponential-backoff retry on transient failures.

    Retries are attempted for:
    - ``APIConnectionError``    — network / SSL errors
    - ``APITimeoutError``       — request timed out
    - ``RateLimitError``        — 429 Too Many Requests
    - ``InternalServerError``   — 5xx from the API
    - ``httpx.ConnectError``    — low-level transport failure
    - ``httpx.ReadTimeout``     — read-side timeout

    Non-retryable errors (400, 401, 403, etc.) are re-raised immediately.

    Args:
        chain:  A LangChain runnable (e.g. ``prompt | llm | parser``).
        inputs: Dict of placeholder values for the prompt template.
        stage:  Pipeline stage name (for per-stage retry count).

    Returns:
        The chain's output (parsed by the output parser if one is attached).

    Raises:
        The last exception if all retries are exhausted.
    """
    return _invoke_with_retry(
        lambda: chain.invoke(inputs, {"callbacks": [_usage_tracker]}), stage
    )


def invoke_llm_with_retry(llm: ChatOpenAI, prompt: Any, stage: str) -> Any:
    """Invoke a bare ``ChatOpenAI.invoke()`` call with retry.

    Use this when the call site is ``llm.invoke(prompt)`` (no LCEL chain).

    Args:
        llm:    A ``ChatOpenAI`` instance from ``get_llm()``.
        prompt: The input to pass to ``llm.invoke()`` (str or message list).
        stage:  Pipeline stage name for retry-count lookup.

    Returns:
        The ``AIMessage`` returned by the LLM.
    """
    def _call():
        return llm.invoke(prompt, {"callbacks": [_usage_tracker]})
    return _invoke_with_retry(_call, stage)


def _invoke_with_retry(fn, stage: str) -> Any:
    """Internal — shared retry loop for any callable."""
    max_retries = _get_retry_count(stage)
    last_exc: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            return fn()
        except (
            APIConnectionError,
            APITimeoutError,
            RateLimitError,
            InternalServerError,
            httpx.ConnectError,
            httpx.ReadTimeout,
            httpx.RemoteProtocolError,
        ) as exc:
            last_exc = exc
            if attempt < max_retries:
                delay = min(
                    _RETRY_BASE_DELAY * (_RETRY_BACKOFF_FACTOR ** attempt),
                    _RETRY_MAX_DELAY,
                )
                jitter = random.uniform(0, delay * 0.5)
                total_delay = delay + jitter
                logger.warning(
                    "LLM call for stage=%s failed (attempt %d/%d): %s — "
                    "retrying in %.1fs …",
                    stage, attempt + 1, max_retries + 1, exc, total_delay,
                )
                time.sleep(total_delay)
            else:
                logger.error(
                    "LLM call for stage=%s failed after %d attempt(s): %s",
                    stage, max_retries + 1, exc,
                )
        except APIStatusError as exc:
            if 400 <= exc.status_code < 500 and exc.status_code != 429:
                raise
            last_exc = exc
            if attempt < max_retries:
                delay = min(_RETRY_BASE_DELAY, _RETRY_MAX_DELAY)
                jitter = random.uniform(0, delay * 0.5)
                total_delay = delay + jitter
                logger.warning(
                    "LLM call for stage=%s failed (attempt %d/%d): HTTP %s — "
                    "retrying in %.1fs …",
                    stage, attempt + 1, max_retries + 1, exc.status_code, total_delay,
                )
                time.sleep(total_delay)
            else:
                raise

    raise last_exc  # type: ignore[misc]


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

    Note:
        The LangChain ``max_retries`` is set to 0 — all retry logic is
        handled by ``invoke_with_retry()`` at the application layer so
        that error classification, backoff, and logging are consistent.
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
        max_retries=0,   # we handle retries ourselves in invoke_with_retry()
        max_tokens=max_tokens,
    )
    if json_mode:
        kwargs["model_kwargs"] = {"response_format": {"type": "json_object"}}

    llm = ChatOpenAI(**kwargs)
    ctx = get_llm_context_window(stage)
    retries = _get_retry_count(stage)
    logger.debug(
        "Created LLM client for stage=%s → model=%s json_mode=%s "
        "max_tokens=%s context_window=%s max_retries=%s",
        stage, model_name, json_mode, max_tokens, ctx, retries,
    )
    return llm
