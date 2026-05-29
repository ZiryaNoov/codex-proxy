"""Integration tests for server endpoints."""

import pytest
from fastapi.testclient import TestClient

from codex_proxy.server import app, configure
from codex_proxy.config import ProxyConfig, ProviderConfig, StoreConfig


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
        from codex_proxy.server import _state
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
