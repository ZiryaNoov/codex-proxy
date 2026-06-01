"""Provider-specific adapters for backend quirks."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ProviderAdapter:
    """Base adapter — no modifications."""

    name: str = "default"

    def adjust_request(self, cc_body: dict) -> dict:
        """Modify the Chat Completions request before sending."""
        return cc_body

    def adjust_headers(self, headers: dict) -> dict:
        """Modify HTTP headers before sending."""
        return headers


def _strip_stream_options(cc_body: dict) -> dict:
    cc_body.pop("stream_options", None)
    return cc_body


class OllamaAdapter(ProviderAdapter):
    """Ollama doesn't support stream_options and doesn't need a real API key."""

    name: str = "ollama"

    def adjust_request(self, cc_body: dict) -> dict:
        return _strip_stream_options(cc_body)


class OpenRouterAdapter(ProviderAdapter):
    """OpenRouter requires HTTP-Referer header for rankings."""

    name: str = "openrouter"

    def adjust_headers(self, headers: dict) -> dict:
        headers.setdefault("HTTP-Referer", "https://github.com/ZiryaNoov/codex-proxy")
        headers.setdefault("X-Title", "codex-proxy")
        return headers


class GroqAdapter(ProviderAdapter):
    """Groq has strict rate limits — no special request modifications needed yet."""

    name: str = "groq"


class AnthropicAdapter(ProviderAdapter):
    """Anthropic uses x-api-key header and anthropic-version."""

    name: str = "anthropic"

    def adjust_request(self, cc_body: dict) -> dict:
        return _strip_stream_options(cc_body)

    def adjust_headers(self, headers: dict) -> dict:
        api_key = headers.pop("Authorization", "").removeprefix("Bearer ").strip()
        headers["x-api-key"] = api_key
        headers["anthropic-version"] = "2023-06-01"
        return headers


class GeminiAdapter(ProviderAdapter):
    """Google Gemini OpenAI-compatible endpoint."""

    name: str = "gemini"

    def adjust_request(self, cc_body: dict) -> dict:
        return _strip_stream_options(cc_body)


class DeepSeekAdapter(ProviderAdapter):
    """DeepSeek is OpenAI-compatible but doesn't support stream_options."""

    name: str = "deepseek"

    def adjust_request(self, cc_body: dict) -> dict:
        return _strip_stream_options(cc_body)


class MistralAdapter(ProviderAdapter):
    """Mistral is OpenAI-compatible but doesn't support stream_options."""

    name: str = "mistral"

    def adjust_request(self, cc_body: dict) -> dict:
        return _strip_stream_options(cc_body)


class CohereAdapter(ProviderAdapter):
    """Cohere OpenAI-compatible endpoint."""

    name: str = "cohere"

    def adjust_request(self, cc_body: dict) -> dict:
        return _strip_stream_options(cc_body)


class NvidiaAdapter(ProviderAdapter):
    """NVIDIA NIM OpenAI-compatible endpoint."""

    name: str = "nvidia"

    def adjust_request(self, cc_body: dict) -> dict:
        return _strip_stream_options(cc_body)


_ADAPTERS: dict[str, type[ProviderAdapter]] = {
    "ollama": OllamaAdapter,
    "openrouter": OpenRouterAdapter,
    "groq": GroqAdapter,
    "anthropic": AnthropicAdapter,
    "gemini": GeminiAdapter,
    "deepseek": DeepSeekAdapter,
    "mistral": MistralAdapter,
    "cohere": CohereAdapter,
    "nvidia": NvidiaAdapter,
}


def get_adapter(provider_name: str) -> ProviderAdapter:
    """Get the adapter for a provider by name. Returns base adapter if unknown."""
    cls = _ADAPTERS.get(provider_name, ProviderAdapter)
    return cls(name=provider_name)
