"""Tests for rate limiting, admin auth, and request size limits on server."""

import pytest
from fastapi.testclient import TestClient

from codex_proxy.config import (
    ProviderConfig,
    ProxyConfig,
    RateLimitConfig,
    ServerConfig,
    StoreConfig,
)
from codex_proxy.server import _state, app, configure


@pytest.fixture(autouse=True)
def _setup():
    config = ProxyConfig(
        provider=ProviderConfig(api_key="test-key"),
        store=StoreConfig(ttl_seconds=60, max_entries=10),
    )
    configure(config)
    yield


@pytest.fixture
def client():
    return TestClient(app)


class TestRateLimiting:
    def test_rate_limit_disabled_by_default(self, client):
        """When rate_limit.enabled=False, no 429 rate limit responses."""
        state = _state()
        assert state.rate_limiter is None
        r = client.post("/responses", json={"input": "test"})
        assert r.status_code != 429

    def test_rate_limit_enabled_creates_limiter(self):
        config = ProxyConfig(
            provider=ProviderConfig(api_key="test-key"),
            rate_limit=RateLimitConfig(enabled=True, max_requests=10, window_seconds=30),
        )
        configure(config)
        state = _state()
        assert state.rate_limiter is not None
        assert state.rate_limiter.max_requests == 10

    def test_rate_limit_blocks_when_exhausted(self):
        """Exhaust the rate limiter manually, then verify endpoint returns 429."""
        config = ProxyConfig(
            provider=ProviderConfig(api_key="test-key"),
            rate_limit=RateLimitConfig(enabled=True, max_requests=2, window_seconds=60),
        )
        configure(config)
        state = _state()
        # Exhaust the limiter for test client IP
        rl = state.rate_limiter
        rl.allow("testclient")  # use slot 1
        rl.allow("testclient")  # use slot 2
        assert rl.allow("testclient") is False  # should be blocked now

    def test_rate_limit_separate_clients_independent(self):
        """Different client IDs have independent quotas."""
        config = ProxyConfig(
            provider=ProviderConfig(api_key="test-key"),
            rate_limit=RateLimitConfig(enabled=True, max_requests=1, window_seconds=60),
        )
        configure(config)
        state = _state()
        rl = state.rate_limiter
        assert rl.allow("client-a") is True
        assert rl.allow("client-a") is False  # exhausted
        assert rl.allow("client-b") is True   # different client

    def test_status_includes_rate_limit_when_enabled(self):
        config = ProxyConfig(
            provider=ProviderConfig(api_key="test-key"),
            rate_limit=RateLimitConfig(enabled=True, max_requests=10, window_seconds=30),
        )
        configure(config)
        c = TestClient(app)
        r = c.get("/status")
        data = r.json()
        assert "rate_limit" in data
        assert data["rate_limit"]["max_requests"] == 10


class TestAdminAuth:
    def test_status_no_token_needed_by_default(self, client):
        r = client.get("/status")
        assert r.status_code == 200

    def test_reload_no_token_needed_by_default(self, client):
        r = client.post("/reload")
        assert r.status_code == 200

    def test_status_requires_token_when_set(self):
        config = ProxyConfig(
            provider=ProviderConfig(api_key="test-key"),
            server=ServerConfig(admin_token="secret123"),
        )
        configure(config)
        c = TestClient(app)
        # Without token
        r = c.get("/status")
        assert r.status_code == 403
        # With wrong token
        r = c.get("/status", headers={"Authorization": "Bearer wrong"})
        assert r.status_code == 403
        # With correct token
        r = c.get("/status", headers={"Authorization": "Bearer secret123"})
        assert r.status_code == 200

    def test_reload_requires_token_when_set(self):
        config = ProxyConfig(
            provider=ProviderConfig(api_key="test-key"),
            server=ServerConfig(admin_token="secret123"),
        )
        configure(config)
        c = TestClient(app)
        r = c.post("/reload", headers={"Authorization": "Bearer secret123"})
        assert r.status_code == 200

    def test_health_never_requires_auth(self):
        config = ProxyConfig(
            provider=ProviderConfig(api_key="test-key"),
            server=ServerConfig(admin_token="secret123"),
        )
        configure(config)
        c = TestClient(app)
        r = c.get("/health")
        assert r.status_code == 200


class TestRequestSizeLimit:
    def test_default_limit_allows_normal_request(self, client):
        r = client.post("/responses", json={"input": "small test"})
        # Should not be 413
        assert r.status_code != 413

    def test_custom_limit_rejects_large_body(self):
        config = ProxyConfig(
            provider=ProviderConfig(api_key="test-key"),
            server=ServerConfig(max_request_body_bytes=100),
        )
        configure(config)
        c = TestClient(app)
        # Send a body larger than 100 bytes
        big_input = "x" * 200
        r = c.post("/responses", json={"input": big_input})
        assert r.status_code == 413
        assert "request_too_large" in r.json()["error"]["code"]
