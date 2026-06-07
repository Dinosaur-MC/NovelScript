"""Tests for services/rate_limiter.py — runs entirely in fakeredis."""

from __future__ import annotations

from app.services.rate_limiter import check_rate_limit, reset_rate_limit


class TestRateLimiter:
    """Test fixed-window rate limiting."""

    def test_first_request_allowed(self, redis_client):
        """First request in a window should be allowed."""
        allowed, remaining = check_rate_limit(redis_client, "test", "user1")
        assert allowed is True
        assert remaining == 4  # 5 max - 1 = 4 remaining

    def test_hits_limit_then_blocked(self, redis_client):
        """After max_requests hits, the next request is blocked."""
        for i in range(5):
            allowed, remaining = check_rate_limit(
                redis_client, "test", "user2", max_requests=5
            )
            assert allowed is True
            assert remaining == 5 - (i + 1)

        # 6th request — blocked
        allowed, remaining = check_rate_limit(
            redis_client, "test", "user2", max_requests=5
        )
        assert allowed is False
        assert remaining == 0

    def test_different_keys_independent(self, redis_client):
        """Rate limits for different keys are independent."""
        # Exhaust user-a
        for _ in range(5):
            check_rate_limit(redis_client, "login", "user-a", max_requests=5)

        # user-b should still be ok
        allowed, _ = check_rate_limit(redis_client, "login", "user-b", max_requests=5)
        assert allowed is True

        # user-a should be blocked
        allowed, _ = check_rate_limit(redis_client, "login", "user-a", max_requests=5)
        assert allowed is False

    def test_different_namespaces_independent(self, redis_client):
        """Rate limits for different namespaces are independent."""
        # Exhaust login-email
        for _ in range(5):
            check_rate_limit(redis_client, "login-email", "x@test.com", max_requests=5)

        # Same key but different namespace should be ok
        allowed, _ = check_rate_limit(
            redis_client, "login-ip", "x@test.com", max_requests=5
        )
        assert allowed is True

    def test_reset_clears_counter(self, redis_client):
        """After reset, the counter starts fresh."""
        for _ in range(5):
            check_rate_limit(redis_client, "test", "reset-me", max_requests=5)

        reset_rate_limit(redis_client, "test", "reset-me")

        allowed, remaining = check_rate_limit(
            redis_client, "test", "reset-me", max_requests=5
        )
        assert allowed is True
        assert remaining == 4

    def test_check_rate_limit_allows_when_redis_unavailable(self, redis_client, monkeypatch):
        """When Redis is unreachable, rate limit is bypassed (allow)."""
        import redis.exceptions

        def _fail(*_a, **_kw):
            raise redis.exceptions.ConnectionError("mock disconnect")

        monkeypatch.setattr(redis_client, "incr", _fail)
        allowed, remaining = check_rate_limit(redis_client, "test", "user-down")
        assert allowed is True
        assert remaining == 5  # max_requests default

    def test_reset_rate_limit_does_not_raise_when_redis_unavailable(self, redis_client, monkeypatch):
        """When Redis is unreachable, reset_rate_limit is a silent no-op."""
        import redis.exceptions

        def _fail(*_a, **_kw):
            raise redis.exceptions.ConnectionError("mock disconnect")

        monkeypatch.setattr(redis_client, "delete", _fail)
        # Should not raise
        reset_rate_limit(redis_client, "test", "down-key")

    def test_window_expires(self, redis_client):
        """After manually expiring the key, counter resets."""
        key = "rate:test:expire-me"
        for _ in range(5):
            check_rate_limit(redis_client, "test", "expire-me", max_requests=5)

        # Manually delete the key to simulate TTL expiry
        assert redis_client.delete(key) == 1

        allowed, remaining = check_rate_limit(
            redis_client, "test", "expire-me", max_requests=5
        )
        assert allowed is True
        assert remaining == 4
