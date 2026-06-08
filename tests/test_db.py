"""Tests for the v5 database layer — engine, models, migrations, CRUD."""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

import pytest

# ── Engine + Models ──────────────────────────────────────────────────────


class TestDbInit:
    """Test database initialization."""

    def test_init_creates_all_tables(self):
        async def _test():
            from codex_proxy.db import init_db
            engine, factory = await init_db(f"sqlite+aiosqlite:///{self._db_path}")
            from sqlalchemy import text
            async with factory() as session:
                result = await session.execute(
                    text("SELECT name FROM sqlite_master WHERE type='table'"))
                tables = sorted(r[0] for r in result.fetchall())
            await engine.dispose()
            assert len(tables) == 14
            assert "users" in tables
            assert "providers" in tables
            assert "request_logs" in tables
            assert "_schema_version" in tables

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            self._db_path = f.name
        try:
            asyncio.run(_test())
        finally:
            os.unlink(self._db_path)

    def test_init_idempotent(self):
        """Calling init_db twice should not fail."""
        async def _test():
            from codex_proxy.db import init_db
            engine1, _ = await init_db(f"sqlite+aiosqlite:///{self._db_path}")
            await engine1.dispose()
            engine2, factory = await init_db(f"sqlite+aiosqlite:///{self._db_path}")
            async with factory() as session:
                from sqlalchemy import text
                result = await session.execute(text("SELECT COUNT(*) FROM _schema_version"))
                version = result.scalar()
                assert version == 1
            await engine2.dispose()

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            self._db_path = f.name
        try:
            asyncio.run(_test())
        finally:
            os.unlink(self._db_path)


class TestModels:
    """Test table definitions."""

    def test_metadata_has_14_tables(self):
        from codex_proxy.db.models import metadata
        assert len(metadata.tables) == 14

    def test_all_expected_tables_exist(self):
        from codex_proxy.db.models import metadata
        expected = {
            "users", "api_keys", "providers", "provider_keys", "models",
            "routing_rules", "request_logs", "budgets", "cost_alerts",
            "plugin_registry", "plugin_instances", "sessions", "_schema_version",
            "documents",
        }
        assert set(metadata.tables.keys()) == expected


# ── CRUD Tests ───────────────────────────────────────────────────────────


@pytest.fixture
def db_session():
    """Provide an async DB session with a temp database."""
    async def _create():
        from codex_proxy.db import init_db
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        engine, factory = await init_db(f"sqlite+aiosqlite:///{db_path}")
        async with factory() as session:
            yield session
        await engine.dispose()
        os.unlink(db_path)

    # We can't use async fixtures easily without pytest-asyncio,
    # so we run the entire test body inside asyncio.run()
    return _create


def _run_db_test(coro):
    """Helper to run an async test with a fresh temp database."""
    async def _wrapper():
        from codex_proxy.db import init_db
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        engine, factory = await init_db(f"sqlite+aiosqlite:///{db_path}")
        async with factory() as session:
            await coro(session)
        await engine.dispose()
        os.unlink(db_path)

    asyncio.run(_wrapper())


class TestCrudUsers:
    """Test user CRUD operations."""

    def test_create_and_get_user(self):
        async def _test(session):
            from codex_proxy.db import crud_users
            user = await crud_users.create_user(
                session, username="zakpro", email="zak@test.com",
                password_hash="hash123")
            assert user["username"] == "zakpro"
            assert user["role"] == "user"
            assert user["is_active"] is True

            fetched = await crud_users.get_user_by_id(session, user["id"])
            assert fetched["username"] == "zakpro"

        _run_db_test(_test)

    def test_get_user_by_username(self):
        async def _test(session):
            from codex_proxy.db import crud_users
            await crud_users.create_user(session, username="alice", email=None, password_hash="h")
            fetched = await crud_users.get_user_by_username(session, "alice")
            assert fetched is not None
            assert fetched["username"] == "alice"

        _run_db_test(_test)

    def test_list_users(self):
        async def _test(session):
            from codex_proxy.db import crud_users
            await crud_users.create_user(session, username="u1", email=None, password_hash="h")
            await crud_users.create_user(session, username="u2", email=None, password_hash="h")
            users = await crud_users.list_users(session)
            assert len(users) == 2

        _run_db_test(_test)

    def test_update_user(self):
        async def _test(session):
            from codex_proxy.db import crud_users
            user = await crud_users.create_user(session, username="bob", email=None, password_hash="h")
            updated = await crud_users.update_user(session, user["id"], role="admin")
            assert updated["role"] == "admin"

        _run_db_test(_test)

    def test_deactivate_user(self):
        async def _test(session):
            from codex_proxy.db import crud_users
            user = await crud_users.create_user(session, username="gone", email=None, password_hash="h")
            deactivated = await crud_users.deactivate_user(session, user["id"])
            assert deactivated["is_active"] is False

        _run_db_test(_test)


class TestCrudKeys:
    """Test API key CRUD operations."""

    def test_create_key_returns_full_key(self):
        async def _test(session):
            from codex_proxy.db import crud_users, crud_keys
            user = await crud_users.create_user(session, username="keyuser", email=None, password_hash="h")
            key_data = await crud_keys.create_api_key(session, user_id=user["id"])
            assert key_data["key"].startswith("cpk_")
            assert len(key_data["key"]) > 20
            assert "key_hash" in key_data

        _run_db_test(_test)

    def test_lookup_key_by_full_string(self):
        async def _test(session):
            from codex_proxy.db import crud_users, crud_keys
            user = await crud_users.create_user(session, username="lookup", email=None, password_hash="h")
            key_data = await crud_keys.create_api_key(session, user_id=user["id"])
            full_key = key_data["key"]
            found = await crud_keys.lookup_key(session, full_key)
            assert found is not None
            assert found["user_id"] == user["id"]

        _run_db_test(_test)

    def test_lookup_revoked_key_returns_none(self):
        async def _test(session):
            from codex_proxy.db import crud_users, crud_keys
            user = await crud_users.create_user(session, username="revoked", email=None, password_hash="h")
            key_data = await crud_keys.create_api_key(session, user_id=user["id"])
            await crud_keys.revoke_key(session, key_data["id"])
            found = await crud_keys.lookup_key(session, key_data["key"])
            assert found is None

        _run_db_test(_test)


class TestCrudProviders:
    """Test provider CRUD operations."""

    def test_create_and_get_provider(self):
        async def _test(session):
            from codex_proxy.db import crud_providers
            p = await crud_providers.create_provider(
                session, name="zai", display_name="Z.AI",
                base_url="https://api.z.ai/api/paas/v4", adapter_name="zai")
            assert p["name"] == "zai"
            fetched = await crud_providers.get_provider_by_name(session, "zai")
            assert fetched["display_name"] == "Z.AI"

        _run_db_test(_test)

    def test_add_provider_key(self):
        async def _test(session):
            from codex_proxy.db import crud_providers
            p = await crud_providers.create_provider(
                session, name="groq", display_name="Groq",
                base_url="https://api.groq.com/openai/v1", adapter_name="groq")
            pk = await crud_providers.add_provider_key(
                session, provider_id=p["id"], encrypted_key="encrypted_value",
                key_prefix="gsk_abc")
            assert pk["key_prefix"] == "gsk_abc"
            keys = await crud_providers.list_provider_keys(session, p["id"])
            assert len(keys) == 1

        _run_db_test(_test)

    def test_create_model_with_pricing(self):
        async def _test(session):
            from codex_proxy.db import crud_providers
            p = await crud_providers.create_provider(
                session, name="test", display_name="Test",
                base_url="https://api.test.com/v1", adapter_name="test")
            m = await crud_providers.create_model(
                session, provider_id=p["id"], model_id="glm-5.1",
                input_price_per_million=0.5, output_price_per_million=1.5)
            assert m["model_id"] == "glm-5.1"
            assert m["input_price_per_million"] == 0.5
            pricing = await crud_providers.get_model_pricing(session, "glm-5.1")
            assert pricing["output_price_per_million"] == 1.5

        _run_db_test(_test)


class TestCrudLogs:
    """Test request log operations."""

    def test_insert_and_get_logs(self):
        async def _test(session):
            from codex_proxy.db import crud_logs
            await crud_logs.insert_log(
                session, request_id="abc123", model="glm-5.1",
                method="http", input_tokens=100, output_tokens=50,
                cost_usd=0.002, latency_ms=450.0, status_code=200)
            await session.commit()
            logs = await crud_logs.get_recent_logs(session)
            assert len(logs) == 1
            assert logs[0]["model"] == "glm-5.1"
            assert logs[0]["input_tokens"] == 100

        _run_db_test(_test)

    def test_count_logs(self):
        async def _test(session):
            from codex_proxy.db import crud_logs
            for i in range(5):
                await crud_logs.insert_log(session, request_id=f"r{i}", model="test", method="http")
            await session.commit()
            count = await crud_logs.count_logs(session)
            assert count == 5

        _run_db_test(_test)


class TestCrudAnalytics:
    """Test analytics aggregation queries."""

    def test_aggregate_costs(self):
        async def _test(session):
            from codex_proxy.db import crud_logs, crud_analytics
            await crud_logs.insert_log(session, request_id="r1", model="glm-5.1", method="http", cost_usd=0.01)
            await crud_logs.insert_log(session, request_id="r2", model="glm-5.1", method="http", cost_usd=0.02)
            await crud_logs.insert_log(session, request_id="r3", model="deepseek-chat", method="http", cost_usd=0.005)
            await session.commit()
            costs = await crud_analytics.aggregate_costs(session)
            assert len(costs) == 2
            glm = next(c for c in costs if c["group_key"] == "glm-5.1")
            assert glm["total_cost"] == pytest.approx(0.03)

        _run_db_test(_test)


class TestCrudBudgets:
    """Test budget CRUD operations."""

    def test_create_budget(self):
        async def _test(session):
            from codex_proxy.db import crud_users, crud_budgets
            user = await crud_users.create_user(session, username="budgeted", email=None, password_hash="h")
            budget = await crud_budgets.create_budget(
                session, user_id=user["id"], daily_limit=10.0, monthly_limit=100.0)
            assert budget["daily_limit"] == 10.0
            assert budget["monthly_limit"] == 100.0

        _run_db_test(_test)

    def test_check_budget_within_limit(self):
        async def _test(session):
            from codex_proxy.db import crud_users, crud_budgets, crud_logs
            user = await crud_users.create_user(session, username="spender", email=None, password_hash="h")
            await crud_budgets.create_budget(session, user_id=user["id"], daily_limit=10.0)
            # Spend $1
            await crud_logs.insert_log(session, user_id=user["id"], request_id="r1", model="test", method="http", cost_usd=1.0)
            await session.commit()
            status = await crud_budgets.check_budget_status(session, user["id"], current_spend=1.0)
            assert status["within_budget"] is True
            assert status["has_budget"] is True

        _run_db_test(_test)
