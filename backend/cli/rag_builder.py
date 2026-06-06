"""In-memory RAG builder — indexes novel chapters for semantic retrieval.

Uses LangChain's FAISS + OpenAIEmbeddings backed by OpenRouter.  On
machines where the SSL_CERT_FILE or CURL_CA_BUNDLE env var points to a
non-standard CA bundle (e.g. PostgreSQL's bundled cert), we patch
os.environ at import time so tiktoken and httpx can download resources.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

# ---------------------------------------------------------------------------
# Fix non-standard CA bundle paths before any HTTP library initialises.
# PostgreSQL on Windows sets SSL_CERT_FILE to its own ca-bundle.crt which
# breaks tiktoken (tries to download cl100k_base tokenizer) and OpenRouter
# TLS verification.  Clear these so Python falls back to certifi.
# ---------------------------------------------------------------------------
for _var in ("SSL_CERT_FILE", "CURL_CA_BUNDLE", "REQUESTS_CA_BUNDLE"):
    if _var in os.environ:
        _val = os.environ[_var]
        if "PostgreSQL" in _val or "postgresql" in _val.lower():
            del os.environ[_var]

from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings

from cli.models import Chapter

logger = logging.getLogger(__name__)

OPENROUTER_BASE = "https://openrouter.ai/api/v1"
EMBEDDING_MODEL = os.getenv(
    "OPENROUTER_EMBEDDING_MODEL", "openai/text-embedding-3-small"
)


def _make_embeddings() -> OpenAIEmbeddings:
    return OpenAIEmbeddings(
        model=EMBEDDING_MODEL,
        openai_api_base=OPENROUTER_BASE,
        openai_api_key=os.getenv("OPENROUTER_API_KEY"),
        model_kwargs={"encoding_format": "float"},
        check_embedding_ctx_length=False,  # send raw text (not token IDs) for OpenRouter compat
    )


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Generate dense embeddings for *texts*.

    Returns a list of float lists, each of dimension 1536 (for
    ``text-embedding-3-small``).  The caller is responsible for
    persisting these (e.g. into ``chapters.embedding``).
    """
    if not texts:
        return []
    emb = _make_embeddings()
    return emb.embed_documents(texts)


def build_index(chapters: list[Chapter]) -> Optional[FAISS]:
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


def build_index_from_db_embeddings(
    chapters: list[Chapter],
    embeddings_map: dict[int, list[float]],
) -> Optional[FAISS]:
    """Build a FAISS index from pre-computed DB embeddings.

    *embeddings_map* maps ``chapter_index → embedding vector``.  Chapters
    whose index is missing from the map are skipped (no API call).

    Returns ``None`` when *chapters* is empty or no embeddings are found.
    """
    if not chapters:
        return None

    docs = []
    vectors = []
    for ch in chapters:
        vec = embeddings_map.get(ch.index)
        if vec is None:
            continue
        docs.append(Document(
            page_content=ch.text,
            metadata={"chapter_index": ch.index, "title": ch.title},
        ))
        vectors.append(vec)

    if not vectors:
        logger.info("No DB embeddings found — FAISS cannot be built from cache.")
        return None

    try:
        import numpy as np
        embedding_model = _make_embeddings()
        # FAISS.from_documents creates embeddings internally; for pre-computed
        # vectors we use FAISS.add_embeddings pattern via from_embeddings
        text_embeddings = list(zip([d.page_content for d in docs], vectors))
        index = FAISS.from_embeddings(
            text_embeddings=text_embeddings,
            embedding=embedding_model,
            metadatas=[d.metadata for d in docs],
        )
        logger.info("FAISS index built from %d cached embedding(s).", len(vectors))
        return index
    except Exception:
        logger.exception("FAISS from DB embeddings failed — RAG will use keyword fallback.")
        return None


def search(index: Optional[FAISS], query: str, k: int = 3,
           fallback_texts: list[str] | None = None) -> list[str]:
    texts = fallback_texts or []
    if index is None:
        logger.info("No FAISS index — using keyword fallback.")
        return _keyword_fallback(query, texts, k)

    try:
        docs = index.similarity_search(query, k=k)
        results = [d.page_content for d in docs]
        logger.debug("FAISS search returned %d result(s).", len(results))
        return results
    except Exception:
        logger.exception("FAISS search failed — using keyword fallback.")
        return _keyword_fallback(query, texts, k)


def _keyword_fallback(query: str, texts: list[str], k: int) -> list[str]:
    if not texts:
        return []
    query_tokens = set(query)
    scored = sorted(
        texts,
        key=lambda t: sum(1 for ch in query_tokens if ch in t),
        reverse=True,
    )
    return scored[:k]
