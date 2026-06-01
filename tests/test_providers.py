"""Tests for provider adapters."""

from codex_proxy.providers import (
    AnthropicAdapter,
    CohereAdapter,
    DeepSeekAdapter,
    GeminiAdapter,
    GroqAdapter,
    MistralAdapter,
    NvidiaAdapter,
    OllamaAdapter,
    OpenRouterAdapter,
    ProviderAdapter,
    get_adapter,
)


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

    def test_groq(self):
        adapter = get_adapter("groq")
        assert isinstance(adapter, GroqAdapter)

    def test_anthropic(self):
        adapter = get_adapter("anthropic")
        assert isinstance(adapter, AnthropicAdapter)

    def test_gemini(self):
        adapter = get_adapter("gemini")
        assert isinstance(adapter, GeminiAdapter)

    def test_deepseek(self):
        adapter = get_adapter("deepseek")
        assert isinstance(adapter, DeepSeekAdapter)

    def test_mistral(self):
        adapter = get_adapter("mistral")
        assert isinstance(adapter, MistralAdapter)

    def test_cohere(self):
        adapter = get_adapter("cohere")
        assert isinstance(adapter, CohereAdapter)

    def test_nvidia(self):
        adapter = get_adapter("nvidia")
        assert isinstance(adapter, NvidiaAdapter)

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


class TestAnthropicAdapter:
    def test_removes_stream_options(self):
        adapter = AnthropicAdapter()
        body = {"model": "claude-sonnet-4-20250514", "stream": True,
                "stream_options": {"include_usage": True}, "messages": []}
        result = adapter.adjust_request(body)
        assert "stream_options" not in result

    def test_sets_x_api_key_header(self):
        adapter = AnthropicAdapter()
        headers = {"Authorization": "Bearer sk-ant-test123", "Content-Type": "application/json"}
        result = adapter.adjust_headers(headers)
        assert result["x-api-key"] == "sk-ant-test123"
        assert "Authorization" not in result

    def test_sets_anthropic_version(self):
        adapter = AnthropicAdapter()
        headers = {"Authorization": "Bearer key"}
        result = adapter.adjust_headers(headers)
        assert result["anthropic-version"] == "2023-06-01"

    def test_empty_auth_falls_through(self):
        adapter = AnthropicAdapter()
        headers = {"Content-Type": "application/json"}
        result = adapter.adjust_headers(headers)
        assert result["x-api-key"] == ""


class TestGeminiAdapter:
    def test_removes_stream_options(self):
        adapter = GeminiAdapter()
        body = {"model": "gemini-2.5-flash", "stream_options": {"include_usage": True}}
        result = adapter.adjust_request(body)
        assert "stream_options" not in result

    def test_keeps_other_fields(self):
        adapter = GeminiAdapter()
        body = {"model": "gemini-2.5-flash", "messages": []}
        result = adapter.adjust_request(body)
        assert result["model"] == "gemini-2.5-flash"


class TestDeepSeekAdapter:
    def test_removes_stream_options(self):
        adapter = DeepSeekAdapter()
        body = {"stream_options": {"include_usage": True}, "messages": []}
        result = adapter.adjust_request(body)
        assert "stream_options" not in result


class TestMistralAdapter:
    def test_removes_stream_options(self):
        adapter = MistralAdapter()
        body = {"stream_options": {"include_usage": True}, "messages": []}
        result = adapter.adjust_request(body)
        assert "stream_options" not in result


class TestCohereAdapter:
    def test_removes_stream_options(self):
        adapter = CohereAdapter()
        body = {"stream_options": {"include_usage": True}, "messages": []}
        result = adapter.adjust_request(body)
        assert "stream_options" not in result


class TestNvidiaAdapter:
    def test_removes_stream_options(self):
        adapter = NvidiaAdapter()
        body = {"stream_options": {"include_usage": True}, "messages": []}
        result = adapter.adjust_request(body)
        assert "stream_options" not in result


class TestBaseAdapter:
    def test_passthrough_request(self):
        adapter = ProviderAdapter()
        body = {"model": "test", "messages": []}
        assert adapter.adjust_request(body) is body

    def test_passthrough_headers(self):
        adapter = ProviderAdapter()
        headers = {"Authorization": "Bearer key"}
        assert adapter.adjust_headers(headers) is headers
