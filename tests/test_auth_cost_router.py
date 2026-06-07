"""Tests for v5 auth, cost calculation, and smart router."""

from __future__ import annotations

import asyncio
import os
import tempfile
from unittest.mock import MagicMock

import pytest


# ── Auth tests ──────────────────────────────────────────────────────────

class TestPasswordHashing:
    """Test password hashing and verification."""

    def test_sha256_fallback_hash_and_verify(self):
        from codex_proxy.auth import hash_password, verify_password
        pw = "supersecret123"
        h = hash_password(pw)
        # Should work with sha256 fallback (bcrypt may or may not be installed)
        assert verify_password(pw, h)

    def test_wrong_password_fails(self):
        from codex_proxy.auth import hash_password, verify_password
        h = hash_password("correct")
        assert not verify_password("wrong", h)

    def test_empty_password(self):
        from codex_proxy.auth import hash_password, verify_password
        h = hash_password("")
        assert verify_password("", h)

    def test_different_hashes_for_same_password(self):
        from codex_proxy.auth import hash_password
        h1 = hash_password("test")
        h2 = hash_password("test")
        # Should be different due to random salt
        assert h1 != h2


class TestJWTTokens:
    """Test JWT token creation and validation."""

    def test_create_and_decode_access_token(self):
        from codex_proxy.auth import create_access_token, decode_token
        token = create_access_token(
            {"sub": "user123", "username": "zak", "role": "admin"},
            "test-secret", expires_minutes=60)
        payload = decode_token(token, "test-secret")
        assert payload["sub"] == "user123"
        assert payload["username"] == "zak"
        assert payload["role"] == "admin"
        assert payload["type"] == "access"
        assert "exp" in payload
        assert "iat" in payload

    def test_create_and_decode_refresh_token(self):
        from codex_proxy.auth import create_refresh_token, decode_token
        token = create_refresh_token(
            {"sub": "user123", "username": "zak", "role": "user"},
            "test-secret", expires_days=7)
        payload = decode_token(token, "test-secret")
        assert payload["type"] == "refresh"
        assert payload["sub"] == "user123"

    def test_expired_token_raises(self):
        from codex_proxy.auth import create_access_token, decode_token
        token = create_access_token(
            {"sub": "u1"}, "secret", expires_minutes=-1)  # already expired
        with pytest.raises(ValueError, match="expired"):
            decode_token(token, "secret")

    def test_wrong_secret_raises(self):
        from codex_proxy.auth import create_access_token, decode_token
        token = create_access_token({"sub": "u1"}, "correct-secret")
        with pytest.raises(ValueError, match="Invalid"):
            decode_token(token, "wrong-secret")

    def test_tampered_token_raises(self):
        from codex_proxy.auth import create_access_token, decode_token
        token = create_access_token({"sub": "u1"}, "secret")
        tampered = token[:-5] + "XXXXX"
        with pytest.raises(ValueError):
            decode_token(tampered, "secret")


class TestAuthUser:
    """Test AuthUser dataclass."""

    def test_repr(self):
        from codex_proxy.auth import AuthUser
        u = AuthUser(user_id="abc", username="zak", role="admin")
        assert "zak" in repr(u)
        assert "admin" in repr(u)


class TestEnsureSecretKey:
    """Test secret key generation."""

    def test_returns_existing_key(self):
        from codex_proxy.auth import ensure_secret_key
        config = MagicMock()
        config.auth.secret_key = "my-key"
        assert ensure_secret_key(config) == "my-key"

    def test_generates_key_when_empty(self):
        from codex_proxy.auth import ensure_secret_key
        config = MagicMock()
        config.auth.secret_key = ""
        key = ensure_secret_key(config)
        assert len(key) > 20
        assert config.auth.secret_key == key  # sets it on config


# ── Cost calculation tests ──────────────────────────────────────────────

class TestCostCalculation:
    """Test cost calculation module."""

    def test_known_model_pricing(self):
        from codex_proxy.cost import calculate_cost_sync
        # glm-5.1: input $0.50/M, output $1.50/M
        cost = calculate_cost_sync("glm-5.1", 1000, 500)
        expected = (1000 * 0.5 / 1_000_000) + (500 * 1.5 / 1_000_000)
        assert cost == pytest.approx(expected, rel=1e-6)

    def test_free_model(self):
        from codex_proxy.cost import calculate_cost_sync
        cost = calculate_cost_sync("qwen3:32b", 10000, 10000)
        assert cost == 0.0

    def test_unknown_model_returns_zero(self):
        from codex_proxy.cost import calculate_cost_sync
        cost = calculate_cost_sync("totally-unknown-model-xyz", 1000, 1000)
        assert cost == 0.0

    def test_zero_tokens(self):
        from codex_proxy.cost import calculate_cost_sync
        cost = calculate_cost_sync("glm-5.1", 0, 0)
        assert cost == 0.0

    def test_large_token_count(self):
        from codex_proxy.cost import calculate_cost_sync
        # 1M input + 1M output for glm-5.1 = $0.50 + $1.50 = $2.00
        cost = calculate_cost_sync("glm-5.1", 1_000_000, 1_000_000)
        assert cost == pytest.approx(2.0, rel=1e-6)

    def test_async_cost_with_db(self):
        """Test async cost calculation with a real DB."""
        async def _test():
            from codex_proxy.db import init_db
            from codex_proxy.db import crud_providers
            from codex_proxy.cost import calculate_cost

            with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
                db_path = f.name
            engine, factory = await init_db(f"sqlite+aiosqlite:///{db_path}")

            # Seed a model with pricing
            async with factory() as session:
                p = await crud_providers.create_provider(
                    session, name="test", display_name="Test",
                    base_url="https://api.test.com/v1", adapter_name="test")
                await crud_providers.create_model(
                    session, provider_id=p["id"], model_id="test-model",
                    input_price_per_million=2.0, output_price_per_million=4.0)

            # Calculate cost — should use DB pricing
            cost = await calculate_cost("test-model", 500000, 500000, factory)
            expected = (500000 * 2.0 / 1_000_000) + (500000 * 4.0 / 1_000_000)
            assert cost == pytest.approx(expected, rel=1e-6)

            # Unknown model — should return 0 (not in DB, not in KNOWN_PRICING)
            cost = await calculate_cost("unknown-model", 100, 100, factory)
            assert cost == 0.0

            await engine.dispose()
            os.unlink(db_path)

        asyncio.run(_test())


# ── Smart Router tests ──────────────────────────────────────────────────

class TestProviderLatency:
    """Test latency tracking."""

    def test_record_and_average(self):
        from codex_proxy.router import ProviderLatency
        lat = ProviderLatency()
        lat.record(100.0, True)
        lat.record(200.0, True)
        lat.record(300.0, True)
        assert lat.average_ms() == 200.0

    def test_errors_excluded_from_average(self):
        from codex_proxy.router import ProviderLatency
        lat = ProviderLatency()
        lat.record(100.0, True)
        lat.record(5000.0, False)
        lat.record(200.0, True)
        assert lat.average_ms() == 150.0  # only successful

    def test_all_errors_returns_inf(self):
        from codex_proxy.router import ProviderLatency
        lat = ProviderLatency()
        lat.record(100.0, False)
        lat.record(200.0, False)
        assert lat.average_ms() == float("inf")

    def test_empty_returns_inf(self):
        from codex_proxy.router import ProviderLatency
        lat = ProviderLatency()
        assert lat.average_ms() == float("inf")

    def test_error_rate(self):
        from codex_proxy.router import ProviderLatency
        lat = ProviderLatency()
        lat.record(100.0, True)
        lat.record(200.0, False)
        lat.record(300.0, True)
        lat.record(400.0, False)
        assert lat.error_rate() == 0.5

    def test_healthy_threshold(self):
        from codex_proxy.router import ProviderLatency
        lat = ProviderLatency()
        for _ in range(4):
            lat.record(100.0, True)
        lat.record(100.0, False)
        assert lat.is_healthy(max_error_rate=0.5)  # 20% errors
        lat.record(100.0, False)
        lat.record(100.0, False)
        lat.record(100.0, False)
        assert not lat.is_healthy(max_error_rate=0.5)  # now > 50%

    def test_rolling_window(self):
        from codex_proxy.router import ProviderLatency
        lat = ProviderLatency()
        # maxlen=100, so fill it up
        for i in range(100):
            lat.record(float(i), True)
        # Add one more
        lat.record(999.0, True)
        # Oldest should be evicted
        assert len(lat.samples) == 100


class TestSmartRouter:
    """Test smart routing strategies."""

    def _make_providers_map(self, names_models: dict[str, list[str]]):
        """Helper to create a fake providers_map."""
        from codex_proxy.server import ProviderState
        from codex_proxy.providers import get_adapter
        import httpx
        providers_map = {}
        client = httpx.AsyncClient()
        for name, models in names_models.items():
            pcfg = MagicMock()
            pcfg.name = name
            pcfg.display_name = name.upper()
            pcfg.base_url = f"https://api.{name}.com/v1"
            pcfg.models = models
            pcfg.effective_api_keys = MagicMock(return_value=["sk-test"])
            providers_map[name] = ProviderState(
                config=pcfg, adapter=get_adapter(name),
                base_url=pcfg.base_url, client=client)
        return providers_map

    def test_fallback_strategy_first_provider(self):
        from codex_proxy.router import SmartRouter
        pmap = self._make_providers_map({
            "zai": ["glm-5.1", "glm-5"],
            "groq": ["llama-4-maverick-17b"],
        })
        router = SmartRouter(strategy="fallback", providers_map=pmap)
        name, _ = router.select_provider("glm-5.1", pmap)
        assert name == "zai"

    def test_fallback_strategy_second_provider(self):
        from codex_proxy.router import SmartRouter
        pmap = self._make_providers_map({
            "zai": ["glm-5.1"],
            "groq": ["llama-4-maverick-17b"],
        })
        router = SmartRouter(strategy="fallback", providers_map=pmap)
        name, _ = router.select_provider("llama-4-maverick-17b", pmap)
        assert name == "groq"

    def test_fallback_skips_unhealthy(self):
        from codex_proxy.router import SmartRouter
        pmap = self._make_providers_map({
            "zai": ["glm-5.1"],
            "groq": ["glm-5.1"],
        })
        router = SmartRouter(strategy="fallback", providers_map=pmap)
        # Make zai unhealthy
        for _ in range(10):
            router.record_latency("zai", 1000.0, success=False)
        name, _ = router.select_provider("glm-5.1", pmap)
        assert name == "groq"

    def test_latency_strategy(self):
        from codex_proxy.router import SmartRouter
        pmap = self._make_providers_map({
            "zai": ["glm-5.1"],
            "groq": ["glm-5.1"],
        })
        router = SmartRouter(strategy="latency", providers_map=pmap)
        # zai is slow, groq is fast
        for _ in range(5):
            router.record_latency("zai", 500.0, success=True)
        for _ in range(5):
            router.record_latency("groq", 50.0, success=True)
        name, _ = router.select_provider("glm-5.1", pmap)
        assert name == "groq"

    def test_weighted_strategy_distributes(self):
        from codex_proxy.router import SmartRouter
        pmap = self._make_providers_map({
            "zai": ["glm-5.1"],
            "groq": ["glm-5.1"],
        })
        router = SmartRouter(strategy="weighted", providers_map=pmap)
        router.set_weights({"zai": 0.8, "groq": 0.2})
        # Run 100 selections
        counts = {"zai": 0, "groq": 0}
        for _ in range(100):
            name, _ = router.select_provider("glm-5.1", pmap)
            counts[name] += 1
        # zai should get ~80%, groq ~20% (with some variance)
        assert counts["zai"] > 50  # rough check
        assert counts["groq"] > 5   # rough check

    def test_single_provider_returns_directly(self):
        from codex_proxy.router import SmartRouter
        pmap = self._make_providers_map({"zai": ["glm-5.1"]})
        router = SmartRouter(strategy="fallback", providers_map=pmap)
        name, _ = router.select_provider("glm-5.1", pmap)
        assert name == "zai"

    def test_unknown_model_uses_fallback(self):
        from codex_proxy.router import SmartRouter
        pmap = self._make_providers_map({"zai": ["glm-5.1"]})
        router = SmartRouter(strategy="fallback", providers_map=pmap)
        name, model = router.select_provider("unknown-model", pmap)
        assert name == "zai"  # falls back to only provider

    def test_get_status(self):
        from codex_proxy.router import SmartRouter
        pmap = self._make_providers_map({
            "zai": ["glm-5.1"],
            "groq": ["llama-4-maverick-17b"],
        })
        router = SmartRouter(strategy="latency", providers_map=pmap)
        router.record_latency("zai", 100.0, True)
        status = router.get_status()
        assert status["strategy"] == "latency"
        assert "zai" in status["providers"]
        assert status["providers"]["zai"]["avg_latency_ms"] == 100.0
        assert status["providers"]["zai"]["healthy"] is True
