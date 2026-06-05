"""Generic BaseCRUD operations tested against the *users* table."""

from __future__ import annotations

import uuid

import pytest

from app.models.sql import User
from app.services.base import BaseCRUD


@pytest.fixture
def user_crud() -> BaseCRUD[User]:
    return BaseCRUD(User)


# ---------------------------------------------------------------------------
# 1. create + get
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_and_get(db, user_crud: BaseCRUD[User]):
    """Creating a row then fetching by PK returns the same data."""
    uid = uuid.uuid4()
    username = f"crud_create_{uid.hex[:6]}"

    user = User(
        id=uid,
        username=username,
        email=f"{username}@test.local",
        password_hash="hash",
    )
    created = await user_crud.create(db, user)
    assert created.id == uid
    assert created.username == username

    fetched = await user_crud.get(db, uid)
    assert fetched is not None
    assert fetched.email == f"{username}@test.local"


# ---------------------------------------------------------------------------
# 2. list pagination
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_pagination(db, user_crud: BaseCRUD[User]):
    """Listing with offset/limit respects pagination parameters."""
    # Create two users
    for i in range(2):
        uid = uuid.uuid4()
        user = User(
            id=uid,
            username=f"crud_list_{i}_{uid.hex[:4]}",
            email=f"crud_list_{i}_{uid.hex[:4]}@test.local",
            password_hash="h",
        )
        db.add(user)
    await db.flush()

    rows, total = await user_crud.list(db, offset=0, limit=1)
    assert len(rows) == 1
    assert total >= 2  # at least the two we just inserted


# ---------------------------------------------------------------------------
# 3. update
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update(db, user_crud: BaseCRUD[User]):
    """Updating a field persists the change."""
    uid = uuid.uuid4()
    username = f"crud_upd_{uid.hex[:6]}"
    user = User(
        id=uid,
        username=username,
        email=f"{username}@test.local",
        password_hash="h",
    )
    await user_crud.create(db, user)

    updated = await user_crud.update(db, uid, {"display_name": "UpdatedName"})
    assert updated is not None
    assert updated.display_name == "UpdatedName"

    # Double-check with a fresh get
    fetched = await user_crud.get(db, uid)
    assert fetched is not None
    assert fetched.display_name == "UpdatedName"


# ---------------------------------------------------------------------------
# 4. delete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete(db, user_crud: BaseCRUD[User]):
    """Deleting a row removes it and returns True; second delete returns False."""
    uid = uuid.uuid4()
    username = f"crud_del_{uid.hex[:6]}"
    user = User(
        id=uid,
        username=username,
        email=f"{username}@test.local",
        password_hash="h",
    )
    await user_crud.create(db, user)

    result = await user_crud.delete(db, uid)
    assert result is True

    fetched = await user_crud.get(db, uid)
    assert fetched is None

    # Re-delete should return False
    result2 = await user_crud.delete(db, uid)
    assert result2 is False
