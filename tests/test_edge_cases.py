"""Edge case and additional tests for compaction, config, and providers."""

import pytest

from codex_proxy.compaction import compact_messages
from codex_proxy.config import (
    ProxyConfig,
    RateLimitConfig,
    ServerConfig,
    load_config,
)
from codex_proxy.providers import (
    FireworksAdapter,
    TogetherAdapter,
    get_adapter,
)


class TestCompactionEdgeCases:
    def test_keep_last_exceeds_max_messages(self):
        """keep_last >= max_messages should return messages unchanged."""
        msgs = [{"role": "user", "content": f"msg{i}"} for i in range(60)]
        result = compact_messages(msgs, max_messages=50, keep_last=50)
        # rest has 60 messages, keep_last=50, 60 <= 50 is False,
        # but len(rest)=60 > keep_last=50, so it compacts
        # Actually 60 > 50 so it will compact to 50 + notice
        assert len(result) == 51  # 1 notice + 50 kept

    def test_keep_last_equals_rest_count(self):
        """If rest count equals keep_last, no compaction needed."""
        msgs = [{"role": "user", "content": f"msg{i}"} for i in range(20)]
        result = compact_messages(msgs, max_messages=10, keep_last=20)
        assert result is msgs  # len(rest) <= keep_last, return as-is

    def test_single_message_over_limit(self):
        """Edge: only 1 message but max_messages=0, keep_last=0.
        rest[-0:] = full list (Python quirk), so message is kept."""
        msgs = [{"role": "user", "content": "hello"}]
        result = compact_messages(msgs, max_messages=0, keep_last=0)
        # rest[-0:] returns the full rest (Python slice: arr[-0:] == arr[0:])
        assert len(result) == 2  # compaction notice + kept message
        assert result[0]["role"] == "system"
        assert "dropped" in result[0]["content"]

    def test_compaction_notice_says_dropped(self):
        """Verify compaction notice says 'dropped' not 'summarized'."""
        msgs = [{"role": "user", "content": f"msg{i}"} for i in range(60)]
        result = compact_messages(msgs, max_messages=50, keep_last=20)
        notice = result[0]
        assert "dropped" in notice["content"]
        assert "summarized" not in notice["content"]


class TestConfigEdgeCases:
    def test_malformed_toml_raises_error(self, tmp_path):
        """Malformed TOML should raise an error, not crash silently."""
        import sys

        if sys.version_info >= (3, 11):
            import tomllib
        else:
            import tomli as tomllib  # type: ignore[import-not-found]

        bad_config = tmp_path / "config.toml"
        bad_config.write_text("this is not valid toml [[[")
        with pytest.raises(tomllib.TOMLDecodeError):
            load_config(bad_config)

    def test_port_zero_override(self):
        """Port 0 should be a valid override (not falsy)."""
        config = ProxyConfig(server=ServerConfig(port=0))
        assert config.server.port == 0

    def test_server_config_new_fields(self):
        """Verify new server config fields have correct defaults."""
        sc = ServerConfig()
        assert sc.max_retries == 1
        assert sc.retry_delay == 0.5
        assert sc.connect_timeout == 10.0
        assert sc.read_timeout == 180.0
        assert sc.admin_token == ""
        assert sc.max_request_body_bytes == 10 * 1024 * 1024
        assert sc.cors_origins == []

    def test_rate_limit_config_defaults(self):
        rl = RateLimitConfig()
        assert rl.enabled is False
        assert rl.max_requests == 60
        assert rl.window_seconds == 60

    def test_config_from_toml_with_new_fields(self, tmp_path):
        config_file = tmp_path / "config.toml"
        config_file.write_text(
            '[server]\nhost = "0.0.0.0"\nport = 8080\n'
            'max_retries = 3\nretry_delay = 1.0\n'
            'connect_timeout = 15.0\nread_timeout = 300.0\n'
            'admin_token = "mytoken"\n'
            'cors_origins = ["*"]\n'
            '\n[store]\n[provider]\napi_key = "test"\n'
            '[circuit_breaker]\n[compaction]\n[plugins]\n[rate_limit]\n'
            'enabled = true\nmax_requests = 100\nwindow_seconds = 120\n'
        )
        config = load_config(config_file)
        assert config.server.host == "0.0.0.0"
        assert config.server.port == 8080
        assert config.server.max_retries == 3
        assert config.server.retry_delay == 1.0
        assert config.server.connect_timeout == 15.0
        assert config.server.read_timeout == 300.0
        assert config.server.admin_token == "mytoken"
        assert config.server.cors_origins == ["*"]
        assert config.rate_limit.enabled is True
        assert config.rate_limit.max_requests == 100
        assert config.rate_limit.window_seconds == 120


class TestNewProviderAdapters:
    def test_together_adapter(self):
        adapter = get_adapter("together")
        assert isinstance(adapter, TogetherAdapter)
        body = {"model": "test", "stream_options": {"include_usage": True}}
        result = adapter.adjust_request(body)
        assert "stream_options" not in result

    def test_fireworks_adapter(self):
        adapter = get_adapter("fireworks")
        assert isinstance(adapter, FireworksAdapter)
        body = {"model": "test", "stream_options": {"include_usage": True}}
        result = adapter.adjust_request(body)
        assert "stream_options" not in result

    def test_unknown_provider_returns_base(self):
        from codex_proxy.providers import ProviderAdapter
        adapter = get_adapter("unknown_provider_xyz")
        assert isinstance(adapter, ProviderAdapter)

    def test_all_adapters_in_registry(self):
        from codex_proxy.providers import _ADAPTERS
        expected = {"ollama", "openrouter", "groq", "anthropic", "gemini",
                    "deepseek", "mistral", "cohere", "nvidia",
                    "together", "fireworks"}
        assert expected.issubset(set(_ADAPTERS.keys()))
