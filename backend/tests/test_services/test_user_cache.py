"""Tests for services/user_cache.py — runs entirely in fakeredis."""

from __future__ import annotations

from app.services.user_cache import (
    get_cached_user,
    invalidate_user_cache,
    set_cached_user,
)


class TestUserCache:
    """Test user profile caching."""

    USER_DATA = {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "username": "testuser",
        "email": "test@example.com",
        "role": "user",
        "is_active": True,
        "password_hash": "$argon2id$fakehash",
    }

    def test_cache_miss_returns_none(self, redis_client):
        """A never-cached user returns None."""
        result = get_cached_user(redis_client, "unknown-user-id")
        assert result is None

    def test_cache_hit_after_set(self, redis_client):
        """Setting then getting returns the same data."""
        uid = self.USER_DATA["id"]
        set_cached_user(redis_client, uid, self.USER_DATA)

        cached = get_cached_user(redis_client, uid)
        assert cached is not None
        assert cached["id"] == uid
        assert cached["username"] == "testuser"
        assert cached["email"] == "test@example.com"
        assert cached["role"] == "user"
        assert cached["is_active"] is True
        assert cached["password_hash"] == "$argon2id$fakehash"

    def test_cache_has_ttl(self, redis_client):
        """The cached entry has a TTL set."""
        uid = self.USER_DATA["id"]
        set_cached_user(redis_client, uid, self.USER_DATA)

        ttl = redis_client.ttl(f"user:{uid}")
        assert 295 <= ttl <= 300, f"Expected ~300s TTL, got {ttl}"

    def test_invalidate_removes_cache(self, redis_client):
        """Invalidate clears the cached entry."""
        uid = self.USER_DATA["id"]
        set_cached_user(redis_client, uid, self.USER_DATA)

        invalidate_user_cache(redis_client, uid)

        cached = get_cached_user(redis_client, uid)
        assert cached is None

    def test_different_users_independent(self, redis_client):
        """Caching user A does not leak to user B."""
        set_cached_user(redis_client, "user-A", self.USER_DATA)

        assert get_cached_user(redis_client, "user-A") is not None
        assert get_cached_user(redis_client, "user-B") is None

    def test_get_cached_user_returns_none_when_redis_unavailable(self, redis_client, monkeypatch):
        """When Redis is unreachable, cache miss is returned (fall through to DB)."""
        import redis.exceptions

        def _fail(*_a, **_kw):
            raise redis.exceptions.ConnectionError("mock disconnect")

        monkeypatch.setattr(redis_client, "get", _fail)
        assert get_cached_user(redis_client, "any-id") is None

    def test_set_cached_user_does_not_raise_when_redis_unavailable(self, redis_client, monkeypatch):
        """When Redis is unreachable, set_cached_user is a silent no-op."""
        import redis.exceptions

        def _fail(*_a, **_kw):
            raise redis.exceptions.ConnectionError("mock disconnect")

        monkeypatch.setattr(redis_client, "setex", _fail)
        # Should not raise
        set_cached_user(redis_client, "down-id", self.USER_DATA)

    def test_invalidate_does_not_raise_when_redis_unavailable(self, redis_client, monkeypatch):
        """When Redis is unreachable, invalidate_user_cache is a silent no-op."""
        import redis.exceptions

        def _fail(*_a, **_kw):
            raise redis.exceptions.ConnectionError("mock disconnect")

        monkeypatch.setattr(redis_client, "delete", _fail)
        # Should not raise
        invalidate_user_cache(redis_client, "down-id")

    def test_set_overwrites_existing(self, redis_client):
        """Setting a cached user twice overwrites the data."""
        uid = self.USER_DATA["id"]
        set_cached_user(redis_client, uid, self.USER_DATA)

        updated = dict(self.USER_DATA, role="admin")
        set_cached_user(redis_client, uid, updated)

        cached = get_cached_user(redis_client, uid)
        assert cached["role"] == "admin"
