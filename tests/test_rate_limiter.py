"""Tests for the in-memory rate limiter."""

import time

from codex_proxy.rate_limiter import RateLimiter


class TestRateLimiterBasic:
    def test_allows_under_limit(self):
        rl = RateLimiter(max_requests=5, window_seconds=60)
        for _ in range(5):
            assert rl.allow("client-a") is True

    def test_blocks_over_limit(self):
        rl = RateLimiter(max_requests=3, window_seconds=60)
        for _ in range(3):
            rl.allow("client-a")
        assert rl.allow("client-a") is False

    def test_separate_clients_independent(self):
        rl = RateLimiter(max_requests=2, window_seconds=60)
        rl.allow("client-a")
        rl.allow("client-a")
        assert rl.allow("client-a") is False
        assert rl.allow("client-b") is True

    def test_window_expiry(self):
        rl = RateLimiter(max_requests=1, window_seconds=1)
        assert rl.allow("c") is True
        assert rl.allow("c") is False
        time.sleep(1.1)
        assert rl.allow("c") is True


class TestRateLimiterReset:
    def test_reset_specific_client(self):
        rl = RateLimiter(max_requests=1, window_seconds=60)
        rl.allow("a")
        rl.allow("b")
        rl.reset("a")
        assert rl.allow("a") is True
        assert rl.allow("b") is False

    def test_reset_all_clients(self):
        rl = RateLimiter(max_requests=1, window_seconds=60)
        rl.allow("a")
        rl.allow("b")
        rl.reset()
        assert rl.allow("a") is True
        assert rl.allow("b") is True


class TestRateLimiterStatus:
    def test_get_status(self):
        rl = RateLimiter(max_requests=10, window_seconds=30)
        rl.allow("a")
        rl.allow("b")
        status = rl.get_status()
        assert status["max_requests"] == 10
        assert status["window_seconds"] == 30
        assert status["active_clients"] == 2

    def test_status_empty(self):
        rl = RateLimiter(max_requests=5, window_seconds=60)
        status = rl.get_status()
        assert status["active_clients"] == 0
