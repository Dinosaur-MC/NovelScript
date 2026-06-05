"""Generic async CRUD base class.

Provides standard create / read / update / delete operations for any
SQLModel table, usable as a mixin or a standalone service dependency.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Generic, Optional, Sequence, TypeVar

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import SQLModel

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=SQLModel)


class BaseCRUD(Generic[T]):
    """Generic async CRUD repository for SQLModel entity *T*.

    Usage::

        user_crud = BaseCRUD[User](User)
        novel = await user_crud.get(db_session, novel_id)
    """

    def __init__(self, model: type[T]) -> None:
        self.model = model

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    async def create(self, db: AsyncSession, obj: T) -> T:
        """Persist a new row and return it."""
        db.add(obj)
        await db.flush()
        await db.refresh(obj)
        logger.debug("Created %s id=%s", self.model.__name__, getattr(obj, "id", "?"))
        return obj

    # ------------------------------------------------------------------
    # Read — single
    # ------------------------------------------------------------------

    async def get(self, db: AsyncSession, pk: uuid.UUID | str) -> Optional[T]:
        """Retrieve a single row by primary key."""
        result = await db.get(self.model, pk)
        return result

    # ------------------------------------------------------------------
    # Read — list with pagination
    # ------------------------------------------------------------------

    async def list(
        self,
        db: AsyncSession,
        *,
        offset: int = 0,
        limit: int = 50,
        order_by: Optional[str] = None,
        filters: Optional[dict[str, Any]] = None,
    ) -> tuple[Sequence[T], int]:
        """Return a page of rows and the total count.

        Args:
            db: Active database session.
            offset: Number of rows to skip.
            limit: Maximum rows to return (capped at 500).
            order_by: Column name to sort by (descending if prefixed with ``-``).
            filters: Simple equality filters (``{"status": "draft"}``).

        Returns:
            Tuple of ``(rows, total_count)``.
        """
        limit = min(limit, 500)

        stmt = select(self.model)

        if filters:
            for col, val in filters.items():
                stmt = stmt.where(getattr(self.model, col) == val)

        # -- ordering --
        if order_by:
            desc = order_by.startswith("-")
            col_name = order_by[1:] if desc else order_by
            col = getattr(self.model, col_name)
            stmt = stmt.order_by(col.desc() if desc else col.asc())
        else:
            # default: newest first (assumes created_at column exists)
            if hasattr(self.model, "created_at"):
                stmt = stmt.order_by(self.model.created_at.desc())  # type: ignore[union-attr]

        # -- count (same filters, no pagination) --
        count_stmt = select(func.count()).select_from(self.model)
        if filters:
            for col, val in filters.items():
                count_stmt = count_stmt.where(getattr(self.model, col) == val)
        total: int = (await db.execute(count_stmt)).scalar_one()

        # -- pagination --
        stmt = stmt.offset(offset).limit(limit)
        result = await db.execute(stmt)
        rows = result.scalars().all()

        return rows, total

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    async def update(
        self,
        db: AsyncSession,
        pk: uuid.UUID | str,
        updates: dict[str, Any],
    ) -> Optional[T]:
        """Partial update of a row by primary key.

        Args:
            db: Active database session.
            pk: Primary key value.
            updates: Dict of column name → new value.
        """
        obj = await self.get(db, pk)
        if obj is None:
            logger.warning(
                "%s pk=%s not found for update.", self.model.__name__, pk
            )
            return None

        for key, value in updates.items():
            if hasattr(obj, key):
                setattr(obj, key, value)

        # Refresh the "updated_at" column if the model has one
        if hasattr(obj, "updated_at"):
            from datetime import datetime, timezone

            setattr(obj, "updated_at", datetime.now(timezone.utc))

        db.add(obj)
        await db.flush()
        await db.refresh(obj)
        logger.debug("Updated %s id=%s", self.model.__name__, pk)
        return obj

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    async def delete(self, db: AsyncSession, pk: uuid.UUID | str) -> bool:
        """Delete a row by primary key.

        Returns:
            ``True`` if a row was deleted, ``False`` if not found.
        """
        obj = await self.get(db, pk)
        if obj is None:
            logger.warning(
                "%s pk=%s not found for deletion.", self.model.__name__, pk
            )
            return False

        await db.delete(obj)
        await db.flush()
        logger.debug("Deleted %s id=%s", self.model.__name__, pk)
        return True
