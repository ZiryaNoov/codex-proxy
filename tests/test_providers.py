"""Tests for provider adapters."""

from codex_proxy.providers import get_adapter, OllamaAdapter, OpenRouterAdapter, ProviderAdapter


class TestGetAdapter:
    def test_default(self):
        adapter = get_adapter("zai")
        assert isinstance(adapter, ProviderAdapter)
        assert adapter.name == "zai"

    def test_ollama(self):
        adapter = get_adapter("ollama")
        assert isinstance(adapter, OllamaAdapter)

    def test_openrouter(self):
        adapter = get_adapter("openrouter")
        assert isinstance(adapter, OpenRouterAdapter)

    def test_unknown_provider(self):
        adapter = get_adapter("some_new_provider")
        assert isinstance(adapter, ProviderAdapter)


class TestOllamaAdapter:
    def test_removes_stream_options(self):
        adapter = OllamaAdapter()
        body = {"model": "qwen3:32b", "stream": True,
                "stream_options": {"include_usage": True},
                "messages": []}
        result = adapter.adjust_request(body)
        assert "stream_options" not in result

    def test_keeps_other_fields(self):
        adapter = OllamaAdapter()
        body = {"model": "qwen3:32b", "messages": [], "temperature": 0.7}
        result = adapter.adjust_request(body)
        assert result["temperature"] == 0.7


class TestOpenRouterAdapter:
    def test_adds_referer(self):
        adapter = OpenRouterAdapter()
        headers = {"Authorization": "Bearer key"}
        result = adapter.adjust_headers(headers)
        assert "HTTP-Referer" in result
        assert "X-Title" in result

    def test_doesnt_override_existing(self):
        adapter = OpenRouterAdapter()
        headers = {"HTTP-Referer": "https://mysite.com"}
        result = adapter.adjust_headers(headers)
        assert result["HTTP-Referer"] == "https://mysite.com"


class TestBaseAdapter:
    def test_passthrough_request(self):
        adapter = ProviderAdapter()
        body = {"model": "test", "messages": []}
        assert adapter.adjust_request(body) is body

    def test_passthrough_headers(self):
        adapter = ProviderAdapter()
        headers = {"Authorization": "Bearer key"}
        assert adapter.adjust_headers(headers) is headers
