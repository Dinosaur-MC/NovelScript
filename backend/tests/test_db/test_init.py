"""Verify that init.sql and SQLModel create_all produce the expected schema."""

from __future__ import annotations

from sqlalchemy import text

EXPECTED_TABLES = [
    "users", "novels", "tasks", "chapters",
    "knowledge_nodes", "knowledge_edges", "operations",
    "dialogues", "audit_logs",
]

EXPECTED_EXTENSIONS = ["uuid-ossp", "vector", "pg_trgm"]


def test_all_tables_exist(db_conn):
    rows = db_conn.execute(text(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public' ORDER BY table_name"
    ))
    table_names = {r[0] for r in rows}
    for t in EXPECTED_TABLES:
        assert t in table_names, f"Table '{t}' is missing"


def test_extensions_installed(db_conn):
    rows = db_conn.execute(text("SELECT extname FROM pg_extension"))
    installed = {r[0] for r in rows}
    for ext in EXPECTED_EXTENSIONS:
        assert ext in installed, f"Extension '{ext}' is not installed"


def test_chapters_hnsw_index_exists(db_conn):
    rows = db_conn.execute(text(
        "SELECT indexname FROM pg_indexes "
        "WHERE indexname = 'idx_chapters_embedding_hnsw'"
    ))
    assert len(rows.fetchall()) == 1, "HNSW index on chapters.embedding not found"


def test_knowledge_nodes_hnsw_index_exists(db_conn):
    rows = db_conn.execute(text(
        "SELECT indexname FROM pg_indexes "
        "WHERE indexname = 'idx_kn_nodes_embedding_hnsw'"
    ))
    assert len(rows.fetchall()) == 1, "HNSW index on knowledge_nodes.embedding not found"
