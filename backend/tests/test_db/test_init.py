"""Verify that init.sql and SQLModel create_all produce the expected schema."""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# 1. All 8 tables exist
# ---------------------------------------------------------------------------

EXPECTED_TABLES = [
    "users",
    "novels",
    "tasks",
    "chapters",
    "knowledge_nodes",
    "knowledge_edges",
    "operations",
    "dialogues",
    "audit_logs",
]


@pytest.mark.asyncio
async def test_all_tables_exist(db_conn):
    """Every table declared in SDS §5.5 exists in the public schema."""
    rows = await db_conn.fetch(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
        ORDER BY table_name
        """
    )
    table_names = {r["table_name"] for r in rows}
    for t in EXPECTED_TABLES:
        assert t in table_names, f"Table '{t}' is missing"


# ---------------------------------------------------------------------------
# 2. Required extensions are installed
# ---------------------------------------------------------------------------

EXPECTED_EXTENSIONS = ["uuid-ossp", "vector", "pg_trgm"]


@pytest.mark.asyncio
async def test_extensions_installed(db_conn):
    """All required PostgreSQL extensions are available."""
    rows = await db_conn.fetch("SELECT extname FROM pg_extension")
    installed = {r["extname"] for r in rows}
    for ext in EXPECTED_EXTENSIONS:
        assert ext in installed, f"Extension '{ext}' is not installed"


# ---------------------------------------------------------------------------
# 3-4. HNSW indexes exist
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chapters_hnsw_index_exists(db_conn):
    """The chapters.embedding column has an HNSW index for cosine similarity."""
    rows = await db_conn.fetch(
        """
        SELECT indexname FROM pg_indexes
        WHERE indexname = 'idx_chapters_embedding_hnsw'
        """
    )
    assert len(rows) == 1, "HNSW index on chapters.embedding not found"


@pytest.mark.asyncio
async def test_knowledge_nodes_hnsw_index_exists(db_conn):
    """The knowledge_nodes.embedding column has an HNSW index for cosine similarity."""
    rows = await db_conn.fetch(
        """
        SELECT indexname FROM pg_indexes
        WHERE indexname = 'idx_kn_nodes_embedding_hnsw'
        """
    )
    assert len(rows) == 1, "HNSW index on knowledge_nodes.embedding not found"
