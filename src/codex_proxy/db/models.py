"""SQLAlchemy Core table definitions for codex-proxy v5."""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    Float,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import Table

# Shared metadata object — all tables register here
metadata = MetaData()

# ── 1. Users ──────────────────────────────────────────────────────────────

users = Table(
    "users", metadata,
    Column("id", String(36), primary_key=True),          # UUID
    Column("username", String(64), nullable=False, unique=True),
    Column("email", String(255), unique=True),
    Column("password_hash", String(128), nullable=False), # bcrypt
    Column("role", String(16), nullable=False, server_default="user"),  # admin|user|viewer
    Column("is_active", Boolean, nullable=False, server_default="1"),
    Column("created_at", String(32), nullable=False),     # ISO 8601
    Column("updated_at", String(32), nullable=False),
)

# ── 2. API Keys (virtual keys for proxy access) ──────────────────────────

api_keys = Table(
    "api_keys", metadata,
    Column("id", String(36), primary_key=True),
    Column("user_id", String(36), nullable=False, index=True),
    Column("key_hash", String(64), nullable=False),       # SHA-256
    Column("key_prefix", String(12), nullable=False),     # "cpk-ABCD..."
    Column("name", String(64), nullable=False, server_default="default"),
    Column("is_revoked", Boolean, nullable=False, server_default="0"),
    Column("last_used_at", String(32), nullable=True),
    Column("created_at", String(32), nullable=False),
)

# ── 3. Providers ─────────────────────────────────────────────────────────

providers = Table(
    "providers", metadata,
    Column("id", String(36), primary_key=True),
    Column("name", String(32), nullable=False),            # adapter name: zai, groq, etc.
    Column("display_name", String(64), nullable=False),
    Column("base_url", String(512), nullable=False),
    Column("adapter_name", String(32), nullable=False),
    Column("extra_headers", Text, server_default="{}"),    # JSON
    Column("is_enabled", Boolean, nullable=False, server_default="1"),
    Column("priority", Integer, nullable=False, server_default="0"),
    Column("created_at", String(32), nullable=False),
    Column("updated_at", String(32), nullable=False),
)

# ── 4. Provider Keys (encrypted API keys per provider) ───────────────────

provider_keys = Table(
    "provider_keys", metadata,
    Column("id", String(36), primary_key=True),
    Column("provider_id", String(36), nullable=False, index=True),
    Column("encrypted_key", Text, nullable=False),         # Fernet-encrypted
    Column("key_prefix", String(12), nullable=False),
    Column("is_enabled", Boolean, nullable=False, server_default="1"),
    Column("circuit_state", String(16), nullable=False, server_default="closed"),
    Column("failure_count", Integer, nullable=False, server_default="0"),
    Column("success_count", Integer, nullable=False, server_default="0"),
    Column("last_used_at", String(32), nullable=True),
    Column("created_at", String(32), nullable=False),
)

# ── 5. Models (known models with pricing) ────────────────────────────────

models = Table(
    "models", metadata,
    Column("id", String(36), primary_key=True),
    Column("provider_id", String(36), nullable=False, index=True),
    Column("model_id", String(128), nullable=False),       # e.g. 'glm-5.1'
    Column("display_name", String(128), nullable=True),
    Column("input_price_per_million", Float, nullable=False, server_default="0.0"),
    Column("output_price_per_million", Float, nullable=False, server_default="0.0"),
    Column("is_enabled", Boolean, nullable=False, server_default="1"),
    UniqueConstraint("provider_id", "model_id", name="uq_provider_model"),
)

# ── 6. Routing Rules ─────────────────────────────────────────────────────

routing_rules = Table(
    "routing_rules", metadata,
    Column("id", String(36), primary_key=True),
    Column("priority", Integer, nullable=False, server_default="0"),
    Column("name", String(64), nullable=False),
    Column("match_model", String(256), nullable=True),     # exact or regex
    Column("match_pattern", Text, nullable=True),          # JSON criteria
    Column("strategy", String(16), nullable=False, server_default="fallback"),
    Column("target_providers", Text, nullable=False),      # JSON array of provider IDs
    Column("target_model", String(128), nullable=True),    # override model at target
    Column("weights", Text, nullable=True),                # JSON {provider_id: weight}
    Column("is_enabled", Boolean, nullable=False, server_default="1"),
    Column("created_at", String(32), nullable=False),
)

# ── 7. Request Logs (append-only time-series) ───────────────────────────

request_logs = Table(
    "request_logs", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("user_id", String(36), nullable=True, index=True),
    Column("api_key_id", String(36), nullable=True),
    Column("provider_id", String(36), nullable=True, index=True),
    Column("request_id", String(16), nullable=False),      # hex request ID
    Column("model", String(128), nullable=False),
    Column("method", String(4), nullable=False),            # http|ws
    Column("input_tokens", Integer, nullable=False, server_default="0"),
    Column("output_tokens", Integer, nullable=False, server_default="0"),
    Column("total_tokens", Integer, nullable=False, server_default="0"),
    Column("cost_usd", Float, nullable=False, server_default="0.0"),
    Column("latency_ms", Float, nullable=False, server_default="0.0"),
    Column("status_code", Integer, nullable=True),
    Column("error_message", Text, nullable=True),
    Column("is_stream", Boolean, nullable=False, server_default="0"),
    Column("created_at", String(32), nullable=False),
    Index("ix_request_logs_created", "created_at"),
    Index("ix_request_logs_user", "user_id"),
    Index("ix_request_logs_provider", "provider_id"),
)

# ── 8. Budgets ───────────────────────────────────────────────────────────

budgets = Table(
    "budgets", metadata,
    Column("id", String(36), primary_key=True),
    Column("user_id", String(36), nullable=False),
    Column("daily_limit", Float, nullable=True),            # USD, NULL=unlimited
    Column("monthly_limit", Float, nullable=True),
    Column("alert_threshold", Float, nullable=False, server_default="0.8"),
    Column("webhook_url", String(512), nullable=True),
    Column("created_at", String(32), nullable=False),
    Column("updated_at", String(32), nullable=False),
    UniqueConstraint("user_id", name="uq_budget_user"),
)

# ── 9. Cost Alerts ───────────────────────────────────────────────────────

cost_alerts = Table(
    "cost_alerts", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("user_id", String(36), nullable=False),
    Column("budget_id", String(36), nullable=False),
    Column("alert_type", String(32), nullable=False),      # daily_80%, monthly_100%, etc.
    Column("message", Text, nullable=False),
    Column("current_spend", Float, nullable=False),
    Column("limit_amount", Float, nullable=False),
    Column("is_acknowledged", Boolean, nullable=False, server_default="0"),
    Column("triggered_at", String(32), nullable=False),
    Column("acknowledged_at", String(32), nullable=True),
)

# ── 10. Plugin Registry (marketplace catalog) ────────────────────────────

plugin_registry = Table(
    "plugin_registry", metadata,
    Column("id", String(128), primary_key=True),            # com.example.my-plugin
    Column("name", String(64), nullable=False),
    Column("version", String(16), nullable=False),
    Column("description", Text, nullable=True),
    Column("author", String(64), nullable=True),
    Column("download_url", String(512), nullable=False),
    Column("checksum_sha256", String(64), nullable=False),
    Column("downloads", Integer, nullable=False, server_default="0"),
    Column("created_at", String(32), nullable=False),
)

# ── 11. Plugin Instances (installed plugins per user) ─────────────────────

plugin_instances = Table(
    "plugin_instances", metadata,
    Column("id", String(36), primary_key=True),
    Column("user_id", String(36), nullable=False, index=True),
    Column("plugin_registry_id", String(128), nullable=True),
    Column("config_json", Text, server_default="{}"),
    Column("is_enabled", Boolean, nullable=False, server_default="1"),
    Column("installed_at", String(32), nullable=False),
)

# ── 12. Sessions (JWT refresh token storage) ─────────────────────────────

sessions = Table(
    "sessions", metadata,
    Column("id", String(36), primary_key=True),             # refresh token JTI
    Column("user_id", String(36), nullable=False, index=True),
    Column("expires_at", String(32), nullable=False),
    Column("created_at", String(32), nullable=False),
)

# ── 13. Schema Version (migration tracking) ──────────────────────────────

_schema_version = Table(
    "_schema_version", metadata,
    Column("version", Integer, primary_key=True),
)
