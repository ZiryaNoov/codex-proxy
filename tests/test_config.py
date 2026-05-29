"""Tests for config loading."""

import os
import tempfile
from pathlib import Path

import pytest

from codex_proxy.config import (
    load_config, write_example_config, ProviderConfig, ServerConfig,
    StoreConfig, ProxyConfig,
)


class TestLoadConfigDefaults:
    def test_no_config_file(self, tmp_path):
        config = load_config(tmp_path / "nonexistent.toml")
        assert config.server.host == "127.0.0.1"
        assert config.server.port == 4242
        assert config.provider.name == "zai"

    def test_with_env_vars(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CODEX_PROXY_API_KEY", "test-key")
        monkeypatch.setenv("CODEX_PROXY_BASE_URL", "https://custom.api/v1")
        config = load_config(tmp_path / "nonexistent.toml")
        assert config.provider.api_key == "test-key"
        assert config.provider.base_url == "https://custom.api/v1"


class TestEffectiveApiKey:
    def test_direct_key(self):
        p = ProviderConfig(api_key="direct-key")
        assert p.effective_api_key() == "direct-key"

    def test_env_key(self, monkeypatch):
        monkeypatch.setenv("MY_KEY", "env-key")
        p = ProviderConfig(api_key_env="MY_KEY")
        assert p.effective_api_key() == "env-key"

    def test_fallback(self):
        p = ProviderConfig()
        assert p.effective_api_key() == ""

    def test_direct_takes_priority(self, monkeypatch):
        monkeypatch.setenv("MY_KEY", "env-key")
        p = ProviderConfig(api_key="direct", api_key_env="MY_KEY")
        assert p.effective_api_key() == "direct"


class TestWriteExampleConfig:
    def test_creates_file(self, tmp_path):
        path = write_example_config(tmp_path / "config.toml")
        assert path.exists()
        content = path.read_text()
        assert "[server]" in content
        assert "[provider]" in content
        assert "[store]" in content

    def test_parseable(self, tmp_path):
        path = write_example_config(tmp_path / "config.toml")
        config = load_config(path)
        assert config.provider.name == "zai"
        assert config.store.ttl_seconds == 600


class TestStoreConfig:
    def test_defaults(self):
        s = StoreConfig()
        assert s.ttl_seconds == 600
        assert s.max_entries == 100
