"""Tests for config loading."""



from codex_proxy.config import (
    CircuitBreakerConfig,
    CompactionConfig,
    PluginConfig,
    ProviderConfig,
    StoreConfig,
    load_config,
    write_example_config,
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


class TestCircuitBreakerConfig:
    def test_defaults(self):
        cb = CircuitBreakerConfig()
        assert cb.enabled is True
        assert cb.failure_threshold == 5
        assert cb.recovery_timeout == 30.0

    def test_from_toml(self, tmp_path):
        config_file = tmp_path / "config.toml"
        config_file.write_text(
            '[circuit_breaker]\nenabled = false\nfailure_threshold = 3\nrecovery_timeout = 60.0\n'
            '\n[server]\n[store]\n[provider]\napi_key = "test"\n'
        )
        config = load_config(config_file)
        assert config.circuit_breaker.enabled is False
        assert config.circuit_breaker.failure_threshold == 3
        assert config.circuit_breaker.recovery_timeout == 60.0


class TestCompactionConfig:
    def test_defaults(self):
        c = CompactionConfig()
        assert c.enabled is True
        assert c.max_messages == 50
        assert c.keep_last == 20

    def test_from_toml(self, tmp_path):
        config_file = tmp_path / "config.toml"
        config_file.write_text(
            '[compaction]\nenabled = false\nmax_messages = 30\nkeep_last = 10\n'
            '\n[server]\n[store]\n[provider]\napi_key = "test"\n'
        )
        config = load_config(config_file)
        assert config.compaction.enabled is False
        assert config.compaction.max_messages == 30
        assert config.compaction.keep_last == 10


class TestEffectiveApiKeys:
    def test_single_key(self):
        p = ProviderConfig(api_key="sk-test")
        assert p.effective_api_keys() == ["sk-test"]

    def test_key_list(self):
        p = ProviderConfig(api_keys=["a", "b", "c"])
        assert p.effective_api_keys() == ["a", "b", "c"]

    def test_env_keys(self, monkeypatch):
        monkeypatch.setenv("KEY_A", "val_a")
        monkeypatch.setenv("KEY_B", "val_b")
        p = ProviderConfig(api_keys_env=["KEY_A", "KEY_B"])
        assert p.effective_api_keys() == ["val_a", "val_b"]

    def test_mixed(self, monkeypatch):
        monkeypatch.setenv("ENV_KEY", "env_val")
        p = ProviderConfig(api_keys=["literal"], api_keys_env=["ENV_KEY"])
        assert p.effective_api_keys() == ["literal", "env_val"]

    def test_empty(self):
        p = ProviderConfig()
        assert p.effective_api_keys() == []

    def test_from_toml(self, tmp_path):
        config_file = tmp_path / "config.toml"
        config_file.write_text(
            '[provider]\napi_keys = ["k1", "k2"]\napi_key = "fallback"\n'
            '\n[server]\n[store]\n[circuit_breaker]\n[compaction]\n'
        )
        config = load_config(config_file)
        assert config.provider.effective_api_keys() == ["k1", "k2"]


class TestPluginConfig:
    def test_defaults(self):
        p = PluginConfig()
        assert p.enabled is False
        assert p.plugins == []

    def test_from_toml(self, tmp_path):
        config_file = tmp_path / "config.toml"
        config_file.write_text(
            '[plugins]\nenabled = true\nplugins = ["codex_proxy.plugins_builtin.LoggingPlugin"]\n'
            '\n[server]\n[store]\n[provider]\napi_key = "test"\n[circuit_breaker]\n[compaction]\n'
        )
        config = load_config(config_file)
        assert config.plugins.enabled is True
        assert len(config.plugins.plugins) == 1
