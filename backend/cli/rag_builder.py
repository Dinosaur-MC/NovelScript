"""In-memory RAG builder — indexes novel chapters for semantic retrieval.

Uses LangChain's FAISS wrapper with OpenRouter embeddings.  When the
OpenRouter API is unavailable the module falls back to keyword-based
search so the pipeline can still function in degraded mode.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings

from cli.models import Chapter

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OPENROUTER_BASE = "https://openrouter.ai/api/v1"
EMBEDDING_MODEL = os.getenv(
    "OPENROUTER_EMBEDDING_MODEL", "openai/text-embedding-3-small"
)

# ---------------------------------------------------------------------------
# Embeddings factory
# ---------------------------------------------------------------------------


def _make_embeddings() -> OpenAIEmbeddings:
    """Build an OpenAIEmbeddings instance pointed at OpenRouter."""
    return OpenAIEmbeddings(
        model=EMBEDDING_MODEL,
        openai_api_base=OPENROUTER_BASE,
        openai_api_key=os.getenv("OPENROUTER_API_KEY"),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_index(chapters: list[Chapter]) -> Optional[FAISS]:
    """Build a FAISS vector index from chapter texts.

    Each chapter becomes a Document with metadata `chapter_index` and `title`.

    Args:
        chapters: List of Chapter objects to index.

    Returns:
        A FAISS vectorstore, or ``None`` if embedding fails (keyword fallback).
    """
    if not chapters:
        logger.warning("No chapters to index — returning None.")
        return None

    documents = [
        Document(
            page_content=ch.text,
            metadata={"chapter_index": ch.index, "title": ch.title},
        )
        for ch in chapters
    ]

    embeddings = _make_embeddings()

    try:
        index = FAISS.from_documents(documents, embeddings)
        logger.info("FAISS index built with %d document(s).", len(documents))
        return index
    except Exception:
        logger.exception("FAISS index build failed — RAG will use keyword fallback.")
        return None


def search(index: Optional[FAISS], query: str, k: int = 3) -> list[str]:
    """Search the FAISS index for the top-*k* most relevant chunks.

    Falls back to keyword search when *index* is ``None`` or the search fails.

    Args:
        index: A FAISS vectorstore or ``None``.
        query: The search query string.
        k: Number of results to return.

    Returns:
        List of document page-content strings.
    """
    if index is None:
        logger.info("No FAISS index — returning empty results.")
        return _keyword_fallback(query, [], k)

    try:
        docs = index.similarity_search(query, k=k)
        results = [d.page_content for d in docs]
        logger.debug("FAISS search returned %d result(s) for query.", len(results))
        return results
    except Exception:
        logger.exception("FAISS search failed — using keyword fallback.")
        return _keyword_fallback(query, [], k)


# ---------------------------------------------------------------------------
# Keyword fallback
# ---------------------------------------------------------------------------


def _keyword_fallback(query: str, texts: list[str], k: int) -> list[str]:
    """Simple keyword-overlap search as a degraded fallback."""
    if not texts:
        return []
    query_tokens = set(query)
    scored = sorted(
        texts,
        key=lambda t: sum(1 for ch in query_tokens if ch in t),
        reverse=True,
    )
    return scored[:k]
