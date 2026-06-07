"""Tests for services/token_blacklist.py — runs entirely in fakeredis."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.token_blacklist import blacklist_token, is_blacklisted


class TestTokenBlacklist:
    """Test JWT token revocation via Redis blacklist."""

    def test_is_blacklisted_returns_false_for_unknown_jti(self, redis_client):
        """A jti that was never blacklisted should return False."""
        assert is_blacklisted(redis_client, "abc123neverblacklisted") is False

    def test_blacklist_then_check(self, redis_client):
        """After blacklisting, is_blacklisted returns True."""
        jti = "test-jti-001"
        expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

        blacklist_token(redis_client, jti, expires_at)
        assert is_blacklisted(redis_client, jti) is True

    def test_blacklist_different_jti_independent(self, redis_client):
        """Blacklisting one jti does not affect another."""
        expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        blacklist_token(redis_client, "jti-A", expires_at)

        assert is_blacklisted(redis_client, "jti-A") is True
        assert is_blacklisted(redis_client, "jti-B") is False

    def test_blacklist_sets_ttl(self, redis_client):
        """The blacklist key should have an expiry set."""
        jti = "test-jti-ttl"
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=5)

        blacklist_token(redis_client, jti, expires_at)
        ttl = redis_client.ttl(f"bl:{jti}")
        # TTL should be somewhere between 1 and 5 seconds
        assert 1 <= ttl <= 5, f"Expected 1-5s TTL, got {ttl}"

    def test_blacklist_expired_token_sets_min_ttl(self, redis_client):
        """If the token is already expired, TTL floors at 1 second."""
        jti = "test-jti-expired"
        expires_at = datetime.now(timezone.utc) - timedelta(seconds=10)

        blacklist_token(redis_client, jti, expires_at)
        ttl = redis_client.ttl(f"bl:{jti}")
        assert ttl >= 1, f"Expected at least 1s TTL, got {ttl}"
