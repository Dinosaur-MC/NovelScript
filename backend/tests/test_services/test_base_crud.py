"""Generic BaseCRUD operations tested against the *users* table."""

from __future__ import annotations

import uuid

import pytest

from app.models.sql import User
from app.services.base import BaseCRUD


@pytest.fixture
def user_crud() -> BaseCRUD[User]:
    return BaseCRUD(User)


def test_create_and_get(db, user_crud: BaseCRUD[User]):
    uid = uuid.uuid4()
    username = f"crud_create_{uid.hex[:6]}"
    user = User(id=uid, username=username, email=f"{username}@test.local", password_hash="hash")
    created = user_crud.create(db, user)
    assert created.id == uid
    assert created.username == username

    fetched = user_crud.get(db, uid)
    assert fetched is not None
    assert fetched.email == f"{username}@test.local"


def test_list_pagination(db, user_crud: BaseCRUD[User]):
    for i in range(2):
        uid = uuid.uuid4()
        user = User(id=uid, username=f"crud_list_{i}_{uid.hex[:4]}",
                    email=f"crud_list_{i}_{uid.hex[:4]}@test.local", password_hash="h")
        db.add(user)
    db.flush()

    rows, total = user_crud.list(db, offset=0, limit=1)
    assert len(rows) == 1
    assert total >= 2


def test_update(db, user_crud: BaseCRUD[User]):
    uid = uuid.uuid4()
    username = f"crud_upd_{uid.hex[:6]}"
    user = User(id=uid, username=username, email=f"{username}@test.local", password_hash="h")
    user_crud.create(db, user)

    updated = user_crud.update(db, uid, {"display_name": "UpdatedName"})
    assert updated is not None
    assert updated.display_name == "UpdatedName"

    fetched = user_crud.get(db, uid)
    assert fetched is not None
    assert fetched.display_name == "UpdatedName"


def test_delete(db, user_crud: BaseCRUD[User]):
    uid = uuid.uuid4()
    username = f"crud_del_{uid.hex[:6]}"
    user = User(id=uid, username=username, email=f"{username}@test.local", password_hash="h")
    user_crud.create(db, user)

    assert user_crud.delete(db, uid) is True
    assert user_crud.get(db, uid) is None
    assert user_crud.delete(db, uid) is False
