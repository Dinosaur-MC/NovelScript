"""Generic CRUD base class — synchronous (no event-loop issues on Windows)."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Generic, Optional, Sequence, TypeVar

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlmodel import SQLModel

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=SQLModel)


class BaseCRUD(Generic[T]):
    """Generic CRUD repository for SQLModel entity *T*.

    Usage::

        user_crud = BaseCRUD[User](User)
        novel = user_crud.get(db_session, novel_id)
    """

    def __init__(self, model: type[T]) -> None:
        self.model = model

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def create(self, db: Session, obj: T) -> T:
        """Persist a new row and return it."""
        db.add(obj)
        db.flush()
        db.refresh(obj)
        logger.debug("Created %s id=%s", self.model.__name__, getattr(obj, "id", "?"))
        return obj

    # ------------------------------------------------------------------
    # Read — single
    # ------------------------------------------------------------------

    def get(self, db: Session, pk: uuid.UUID | str) -> Optional[T]:
        """Retrieve a single row by primary key."""
        return db.get(self.model, pk)

    # ------------------------------------------------------------------
    # Read — list with pagination
    # ------------------------------------------------------------------

    def list(
        self,
        db: Session,
        *,
        offset: int = 0,
        limit: int = 50,
        order_by: Optional[str] = None,
        filters: Optional[dict[str, Any]] = None,
    ) -> tuple[Sequence[T], int]:
        """Return a page of rows and the total count."""
        limit = min(limit, 500)

        stmt = select(self.model)

        if filters:
            for col, val in filters.items():
                stmt = stmt.where(getattr(self.model, col) == val)

        if order_by:
            desc = order_by.startswith("-")
            col_name = order_by[1:] if desc else order_by
            col = getattr(self.model, col_name)
            stmt = stmt.order_by(col.desc() if desc else col.asc())
        elif hasattr(self.model, "created_at"):
            stmt = stmt.order_by(self.model.created_at.desc())  # type: ignore[union-attr]

        count_stmt = select(func.count()).select_from(self.model)
        if filters:
            for col, val in filters.items():
                count_stmt = count_stmt.where(getattr(self.model, col) == val)
        total: int = db.execute(count_stmt).scalar_one()

        stmt = stmt.offset(offset).limit(limit)
        result = db.execute(stmt)
        rows = result.scalars().all()

        return rows, total

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def update(
        self, db: Session, pk: uuid.UUID | str, updates: dict[str, Any]
    ) -> Optional[T]:
        obj = self.get(db, pk)
        if obj is None:
            logger.warning("%s pk=%s not found for update.", self.model.__name__, pk)
            return None

        for key, value in updates.items():
            if hasattr(obj, key):
                setattr(obj, key, value)

        if hasattr(obj, "updated_at"):
            setattr(obj, "updated_at", datetime.now(timezone.utc))

        db.add(obj)
        db.flush()
        db.refresh(obj)
        logger.debug("Updated %s id=%s", self.model.__name__, pk)
        return obj

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def delete(self, db: Session, pk: uuid.UUID | str) -> bool:
        obj = self.get(db, pk)
        if obj is None:
            logger.warning("%s pk=%s not found for deletion.", self.model.__name__, pk)
            return False

        db.delete(obj)
        db.flush()
        logger.debug("Deleted %s id=%s", self.model.__name__, pk)
        return True
