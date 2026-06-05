"""SQLModel table definitions for all 8 NovelScript tables.

Matches SDS v2.0.0 S5.5 exactly.  Uses ``sa_column`` for types that
SQLModel's ``Field`` does not natively support (*vector*, *JSONB* with
default, CHECK constraints via :class:`CheckConstraint`).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ============================================================================
# 0. users
# ============================================================================

class User(SQLModel, table=True):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "role IN ('admin', 'user')", name="ck_users_role"
        ),
    )

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        sa_column=Column(UUID(as_uuid=True), primary_key=True),
    )
    username: str = Field(
        max_length=150,
        sa_column=Column(String(150), unique=True, nullable=False),
    )
    email: str = Field(
        max_length=320,
        sa_column=Column(String(320), unique=True, nullable=False),
    )
    password_hash: str = Field(
        max_length=255,
        sa_column=Column(String(255), nullable=False),
    )
    display_name: Optional[str] = Field(
        default=None, max_length=200, sa_column=Column(String(200))
    )
    avatar_url: Optional[str] = Field(default=None, sa_column=Column(Text))
    role: str = Field(
        default="user",
        max_length=10,
        sa_column=Column(String(10), nullable=False, default="user"),
    )
    is_active: bool = Field(default=True)
    last_login_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True))
    )
    created_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False, default=_utcnow),
    )
    updated_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False, default=_utcnow),
    )


# ============================================================================
# 1. novels
# ============================================================================

class Novel(SQLModel, table=True):
    __tablename__ = "novels"
    __table_args__ = (
        CheckConstraint(
            "language IN ('zh', 'en')", name="ck_novels_language"
        ),
        CheckConstraint(
            "status IN ('draft', 'processing', 'completed')",
            name="ck_novels_status",
        ),
    )

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        sa_column=Column(UUID(as_uuid=True), primary_key=True),
    )
    user_id: Optional[uuid.UUID] = Field(
        default=None,
        sa_column=Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True),
    )
    title: str = Field(max_length=500, sa_column=Column(String(500), nullable=False))
    author: Optional[str] = Field(
        default=None, max_length=300, sa_column=Column(String(300))
    )
    source_text: Optional[str] = Field(default=None, sa_column=Column(Text))
    word_count: int = Field(default=0, sa_column=Column(Integer, nullable=False, default=0))
    language: str = Field(
        default="zh",
        max_length=5,
        sa_column=Column(String(5), nullable=False, default="zh"),
    )
    status: str = Field(
        default="draft",
        max_length=20,
        sa_column=Column(String(20), nullable=False, default="draft"),
    )
    meta: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column("metadata", JSONB, nullable=False, default={}),
    )
    created_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False, default=_utcnow),
    )
    updated_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False, default=_utcnow),
    )


# ============================================================================
# 2. tasks
# ============================================================================

class Task(SQLModel, table=True):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','preprocessing','converting','completed','failed')",
            name="ck_tasks_status",
        ),
        CheckConstraint(
            "progress >= 0 AND progress <= 100", name="ck_tasks_progress"
        ),
    )

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        sa_column=Column(UUID(as_uuid=True), primary_key=True),
    )
    novel_id: uuid.UUID = Field(
        sa_column=Column(UUID(as_uuid=True), ForeignKey("novels.id"), nullable=False),
    )
    user_id: Optional[uuid.UUID] = Field(
        default=None,
        sa_column=Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True),
    )
    status: str = Field(
        default="pending",
        max_length=30,
        sa_column=Column(String(30), nullable=False, default="pending"),
    )
    progress: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, default=0),
    )
    summary: Optional[str] = Field(default=None, sa_column=Column(Text))
    characters_json: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, default={}),
    )
    script_yaml: Optional[str] = Field(default=None, sa_column=Column(Text))
    script_json: Optional[dict[str, Any]] = Field(
        default=None, sa_column=Column(JSONB)
    )
    script_fountain: Optional[str] = Field(default=None, sa_column=Column(Text))
    error_message: Optional[str] = Field(default=None, sa_column=Column(Text))
    pipeline_config: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, default={}),
    )
    created_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False, default=_utcnow),
    )
    updated_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False, default=_utcnow),
    )


# ============================================================================
# 3. chapters
# ============================================================================

class Chapter(SQLModel, table=True):
    __tablename__ = "chapters"

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        sa_column=Column(UUID(as_uuid=True), primary_key=True),
    )
    novel_id: uuid.UUID = Field(
        sa_column=Column(UUID(as_uuid=True), ForeignKey("novels.id"), nullable=False),
    )
    chapter_index: int = Field(
        sa_column=Column(Integer, nullable=False),
    )
    title: Optional[str] = Field(
        default=None, max_length=500, sa_column=Column(String(500))
    )
    content: Optional[str] = Field(default=None, sa_column=Column(Text))
    embedding: Optional[list[float]] = Field(
        default=None, sa_column=Column(Vector(1536))
    )
    meta: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column("metadata", JSONB, nullable=False, default={}),
    )
    created_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False, default=_utcnow),
    )


# ============================================================================
# 4. knowledge_nodes
# ============================================================================

class KnowledgeNode(SQLModel, table=True):
    __tablename__ = "knowledge_nodes"
    __table_args__ = (
        CheckConstraint(
            "node_type IN ('character','location','item','organization','event','concept')",
            name="ck_kn_nodes_node_type",
        ),
    )

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        sa_column=Column(UUID(as_uuid=True), primary_key=True),
    )
    novel_id: uuid.UUID = Field(
        sa_column=Column(UUID(as_uuid=True), ForeignKey("novels.id"), nullable=False),
    )
    task_id: Optional[uuid.UUID] = Field(
        default=None,
        sa_column=Column(UUID(as_uuid=True), ForeignKey("tasks.id"), nullable=True),
    )
    node_type: str = Field(
        max_length=20,
        sa_column=Column(String(20), nullable=False),
    )
    name: str = Field(
        max_length=300, sa_column=Column(String(300), nullable=False)
    )
    aliases: list[str] = Field(
        default_factory=list,
        sa_column=Column(ARRAY(Text), nullable=False, default=[]),
    )
    description: Optional[str] = Field(default=None, sa_column=Column(Text))
    properties: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, default={}),
    )
    embedding: Optional[list[float]] = Field(
        default=None, sa_column=Column(Vector(1536))
    )
    created_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False, default=_utcnow),
    )
    updated_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False, default=_utcnow),
    )


# ============================================================================
# 5. knowledge_edges
# ============================================================================

class KnowledgeEdge(SQLModel, table=True):
    __tablename__ = "knowledge_edges"

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        sa_column=Column(UUID(as_uuid=True), primary_key=True),
    )
    novel_id: uuid.UUID = Field(
        sa_column=Column(UUID(as_uuid=True), ForeignKey("novels.id"), nullable=False),
    )
    task_id: Optional[uuid.UUID] = Field(
        default=None,
        sa_column=Column(UUID(as_uuid=True), ForeignKey("tasks.id"), nullable=True),
    )
    source_node_id: uuid.UUID = Field(
        sa_column=Column(
            UUID(as_uuid=True), ForeignKey("knowledge_nodes.id"), nullable=False
        ),
    )
    target_node_id: uuid.UUID = Field(
        sa_column=Column(
            UUID(as_uuid=True), ForeignKey("knowledge_nodes.id"), nullable=False
        ),
    )
    relation: str = Field(
        default="",
        max_length=100,
        sa_column=Column(String(100), nullable=False, default=""),
    )
    weight: float = Field(
        default=1.0,
        sa_column=Column(Float, nullable=False, default=1.0),
    )
    evidence: Optional[str] = Field(default=None, sa_column=Column(Text))
    meta: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column("metadata", JSONB, nullable=False, default={}),
    )
    created_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False, default=_utcnow),
    )


# ============================================================================
# 6. operations
# ============================================================================

class Operation(SQLModel, table=True):
    __tablename__ = "operations"
    __table_args__ = (
        CheckConstraint(
            "type IN ('manual_edit','ai_patch','snapshot','rollback')",
            name="ck_operations_type",
        ),
    )

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        sa_column=Column(UUID(as_uuid=True), primary_key=True),
    )
    task_id: uuid.UUID = Field(
        sa_column=Column(UUID(as_uuid=True), ForeignKey("tasks.id"), nullable=False),
    )
    user_id: Optional[uuid.UUID] = Field(
        default=None,
        sa_column=Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True),
    )
    type: str = Field(
        max_length=20,
        sa_column=Column(String(20), nullable=False),
    )
    target_path: Optional[str] = Field(default=None, sa_column=Column(Text))
    diff_json: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, default={}),
    )
    previous_snapshot: Optional[dict[str, Any]] = Field(
        default=None, sa_column=Column(JSONB)
    )
    applied: bool = Field(default=True)
    created_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False, default=_utcnow),
    )


# ============================================================================
# 7. dialogues
# ============================================================================

class Dialogue(SQLModel, table=True):
    __tablename__ = "dialogues"
    __table_args__ = (
        CheckConstraint(
            "role IN ('user', 'assistant', 'system')",
            name="ck_dialogues_role",
        ),
    )

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        sa_column=Column(UUID(as_uuid=True), primary_key=True),
    )
    task_id: uuid.UUID = Field(
        sa_column=Column(UUID(as_uuid=True), ForeignKey("tasks.id"), nullable=False),
    )
    user_id: Optional[uuid.UUID] = Field(
        default=None,
        sa_column=Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True),
    )
    role: str = Field(
        max_length=10,
        sa_column=Column(String(10), nullable=False),
    )
    content: str = Field(
        default="", sa_column=Column(Text, nullable=False, default="")
    )
    patch_json: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, default={}),
    )
    meta: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column("metadata", JSONB, nullable=False, default={}),
    )
    created_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False, default=_utcnow),
    )


# ============================================================================
# 8. audit_logs
# ============================================================================

class AuditLog(SQLModel, table=True):
    __tablename__ = "audit_logs"
    __table_args__ = (
        CheckConstraint(
            "level IN ('debug','info','warn','error','fatal')",
            name="ck_audit_logs_level",
        ),
    )

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        sa_column=Column(UUID(as_uuid=True), primary_key=True),
    )
    user_id: Optional[uuid.UUID] = Field(
        default=None,
        sa_column=Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True),
    )
    task_id: Optional[uuid.UUID] = Field(
        default=None,
        sa_column=Column(UUID(as_uuid=True), ForeignKey("tasks.id"), nullable=True),
    )
    level: str = Field(
        default="info",
        max_length=10,
        sa_column=Column(String(10), nullable=False, default="info"),
    )
    category: Optional[str] = Field(
        default=None, max_length=100, sa_column=Column(String(100))
    )
    message: str = Field(
        default="", sa_column=Column(Text, nullable=False, default="")
    )
    detail: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, default={}),
    )
    created_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False, default=_utcnow),
    )
