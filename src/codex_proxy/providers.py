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


class OllamaAdapter(ProviderAdapter):
    """Ollama doesn't support stream_options and doesn't need a real API key."""

    name: str = "ollama"

    def adjust_request(self, cc_body: dict) -> dict:
        cc_body.pop("stream_options", None)
        return cc_body


class OpenRouterAdapter(ProviderAdapter):
    """OpenRouter requires HTTP-Referer header for rankings."""

    name: str = "openrouter"

    def adjust_headers(self, headers: dict) -> dict:
        headers.setdefault("HTTP-Referer", "https://github.com/ZakPro/codex-proxy")
        headers.setdefault("X-Title", "codex-proxy")
        return headers


class GroqAdapter(ProviderAdapter):
    """Groq has strict rate limits — no special request modifications needed yet."""

    name: str = "groq"


_ADAPTERS: dict[str, type[ProviderAdapter]] = {
    "ollama": OllamaAdapter,
    "openrouter": OpenRouterAdapter,
    "groq": GroqAdapter,
}


def get_adapter(provider_name: str) -> ProviderAdapter:
    """Get the adapter for a provider by name. Returns base adapter if unknown."""
    cls = _ADAPTERS.get(provider_name, ProviderAdapter)
    return cls(name=provider_name)
