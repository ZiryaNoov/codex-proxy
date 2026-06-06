"""Integration tests for server endpoints."""

import pytest
from fastapi.testclient import TestClient

from codex_proxy.circuit_breaker import CircuitBreaker, CircuitState
from codex_proxy.config import ProviderConfig, ProxyConfig, StoreConfig
from codex_proxy.server import _api_key, _state, app, configure


@pytest.fixture(autouse=True)
def setup_server():
    """Configure the server with test defaults before each test."""
    config = ProxyConfig(
        provider=ProviderConfig(api_key="test-key"),
        store=StoreConfig(ttl_seconds=60, max_entries=10),
    )
    configure(config)
    yield


@pytest.fixture
def client():
    return TestClient(app)


class TestHealthEndpoint:
    def test_health(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert "version" in data

    def test_health_no_backend_check_by_default(self, client):
        r = client.get("/health")
        data = r.json()
        assert "backend" not in data

    def test_health_with_backend_check(self, client):
        r = client.get("/health?check_backend=true")
        data = r.json()
        assert "backend" in data


class TestStatusEndpoint:
    def test_status(self, client):
        r = client.get("/status")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "running"
        assert "uptime_seconds" in data
        assert data["provider"]["name"] == "zai"

    def test_status_has_circuit_breaker(self, client):
        r = client.get("/status")
        data = r.json()
        assert "circuit_breaker" in data
        assert data["circuit_breaker"]["state"] == "closed"


class TestModelsEndpoint:
    def test_models(self, client):
        r = client.get("/models")
        assert r.status_code == 200
        data = r.json()
        assert data["object"] == "list"
        assert len(data["data"]) > 0

    def test_v1_models(self, client):
        r = client.get("/v1/models")
        assert r.status_code == 200


class TestGetResponse:
    def test_not_found(self, client):
        r = client.get("/responses/nonexistent")
        assert r.status_code == 404

    def test_found(self, client):
        state = _state()
        state.store.put("resp_test123", {
            "id": "resp_test123", "object": "response",
            "status": "completed", "output": [],
            "_original_input": [],
        })
        r = client.get("/responses/resp_test123")
        assert r.status_code == 200
        data = r.json()
        assert data["id"] == "resp_test123"
        assert "_original_input" not in data


class TestReloadEndpoint:
    def test_reload(self, client):
        r = client.post("/reload")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "reloaded"


class TestApiKeyExtraction:
    def test_bearer_token(self):
        key = _api_key("Bearer sk-test123")
        assert key == "sk-test123"

    def test_bearer_case_insensitive(self):
        key = _api_key("bearer sk-test123")
        assert key == "sk-test123"

    def test_fallback_to_config(self):
        key = _api_key("")
        assert key == "test-key"

    def test_raw_key_no_bearer(self):
        key = _api_key("raw-key-value")
        assert key == "raw-key-value"


class TestCircuitBreakerIntegration:
    def test_rejects_when_open(self, client):
        state = _state()
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=300.0)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        state.circuit_breaker = cb
        r = client.post("/responses", json={"input": "test"})
        assert r.status_code == 503
        assert "circuit_open" in r.json()["error"]["code"]


class TestAppStateMetrics:
    def test_default_fields(self):
        state = _state()
        assert state.success_count == 0
        assert state.failure_count == 0
        assert state.last_request_time == 0.0

    def test_request_count_increments(self, client):
        state = _state()
        initial = state.request_count
        # This will fail at upstream but request_count should still increment
        client.post("/responses", json={"input": "test"})
        assert state.request_count == initial + 1
        assert state.last_request_time > 0


class TestKeyRotationIntegration:
    def test_single_key_no_rotator(self):
        config = ProxyConfig(provider=ProviderConfig(api_key="test-key"))
        configure(config)
        state = _state()
        assert state.key_rotator is None

    def test_multi_key_creates_rotator(self):
        config = ProxyConfig(provider=ProviderConfig(api_keys=["k1", "k2"]))
        configure(config)
        state = _state()
        assert state.key_rotator is not None
        assert state.key_rotator.key_count == 2

    def test_status_includes_key_rotation(self, client):
        config = ProxyConfig(provider=ProviderConfig(api_keys=["k1", "k2"]))
        configure(config)
        r = client.get("/status")
        data = r.json()
        assert "key_rotation" in data
        assert data["key_rotation"]["total_keys"] == 2


class TestPluginIntegration:
    def test_status_includes_plugins_when_enabled(self, client):
        config = ProxyConfig(
            provider=ProviderConfig(api_key="test-key"),
            plugins=__import__("codex_proxy.config", fromlist=["PluginConfig"]).PluginConfig(
                enabled=True,
                plugins=["codex_proxy.plugins_builtin.LoggingPlugin"],
            ),
        )
        configure(config)
        state = _state()
        assert state.plugin_registry is not None
        r = client.get("/status")
        data = r.json()
        assert "plugins" in data
        assert "logging" in data["plugins"]["loaded"]

    def test_no_plugins_when_disabled(self, client):
        config = ProxyConfig(provider=ProviderConfig(api_key="test-key"))
        configure(config)
        state = _state()
        assert state.plugin_registry is None
        r = client.get("/status")
        data = r.json()
        assert "plugins" not in data
