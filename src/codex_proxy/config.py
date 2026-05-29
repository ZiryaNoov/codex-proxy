"""Config file loading — ~/.codex-proxy/config.toml"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

DEFAULT_DIR = Path.home() / ".codex-proxy"
DEFAULT_CONFIG = DEFAULT_DIR / "config.toml"
DEFAULT_PORT = 4242


@dataclass
class ProviderConfig:
    name: str = "zai"
    display_name: str = "Z.AI"
    base_url: str = "https://api.z.ai/api/paas/v4"
    api_key: str = ""
    api_key_env: str = ""  # env var name to read key from
    models: list[str] = field(default_factory=lambda: ["glm-5.1", "glm-5", "glm-4.7"])
    default_model: str = "glm-5.1"
    stream: bool = True
    extra_headers: dict[str, str] = field(default_factory=dict)

    def effective_api_key(self) -> str:
        if self.api_key:
            return self.api_key
        if self.api_key_env:
            return os.environ.get(self.api_key_env, "")
        return ""


@dataclass
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = DEFAULT_PORT
    log_level: str = "warning"
    log_dir: Path = field(default_factory=lambda: DEFAULT_DIR / "logs")


@dataclass
class ProxyConfig:
    server: ServerConfig = field(default_factory=ServerConfig)
    provider: ProviderConfig = field(default_factory=ProviderConfig)


def load_config(path: Path | None = None) -> ProxyConfig:
    """Load config from TOML file, falling back to defaults."""
    config_path = path or DEFAULT_CONFIG

    if not config_path.exists():
        # Try env var overrides for quick setup
        provider = ProviderConfig(
            base_url=os.environ.get("CODEX_PROXY_BASE_URL", ProviderConfig.base_url),
            api_key=os.environ.get("CODEX_PROXY_API_KEY", ""),
            api_key_env=os.environ.get("CODEX_PROXY_API_KEY_ENV", ""),
            default_model=os.environ.get("CODEX_PROXY_MODEL", "glm-5.1"),
        )
        if not provider.api_key and not provider.api_key_env:
            provider.api_key_env = "OPENAI_API_KEY"
        return ProxyConfig(provider=provider)

    with open(config_path, "rb") as f:
        raw = tomllib.load(f)

    server_raw = raw.get("server", {})
    provider_raw = raw.get("provider", {})

    server = ServerConfig(
        host=server_raw.get("host", "127.0.0.1"),
        port=server_raw.get("port", DEFAULT_PORT),
        log_level=server_raw.get("log_level", "warning"),
        log_dir=Path(server_raw.get("log_dir", str(DEFAULT_DIR / "logs"))),
    )

    provider = ProviderConfig(
        name=provider_raw.get("name", "zai"),
        display_name=provider_raw.get("display_name", "Z.AI"),
        base_url=provider_raw.get("base_url", "https://api.z.ai/api/paas/v4"),
        api_key=provider_raw.get("api_key", ""),
        api_key_env=provider_raw.get("api_key_env", ""),
        models=provider_raw.get("models", ["glm-5.1", "glm-5", "glm-4.7"]),
        default_model=provider_raw.get("default_model", "glm-5.1"),
        stream=provider_raw.get("stream", True),
        extra_headers=provider_raw.get("extra_headers", {}),
    )

    return ProxyConfig(server=server, provider=provider)


def write_example_config(path: Path | None = None) -> Path:
    """Write an example config file."""
    target = path or DEFAULT_CONFIG
    target.parent.mkdir(parents=True, exist_ok=True)

    content = """\
# codex-proxy config — https://github.com/ZakPro/codex-proxy

[server]
host = "127.0.0.1"
port = 4242
log_level = "warning"    # debug, info, warning, error

[provider]
# Provider: Z.AI (GLM models)
name = "zai"
display_name = "Z.AI"
base_url = "https://api.z.ai/api/paas/v4"
api_key = ""             # or set api_key_env below
api_key_env = "OPENAI_API_KEY"  # reads from env var
models = ["glm-5.1", "glm-5", "glm-4.7", "glm-4.6", "glm-4.5-air"]
default_model = "glm-5.1"

# --- Other providers (uncomment one) ---

# [provider]
# name = "groq"
# display_name = "Groq"
# base_url = "https://api.groq.com/openai/v1"
# api_key_env = "GROQ_API_KEY"
# models = ["llama-4-maverick-17b", "mixtral-8x7b-32768"]
# default_model = "llama-4-maverick-17b"

# [provider]
# name = "together"
# display_name = "Together AI"
# base_url = "https://api.together.xyz/v1"
# api_key_env = "TOGETHER_API_KEY"
# models = ["meta-llama/Llama-3.3-70B-Instruct-Turbo"]
# default_model = "meta-llama/Llama-3.3-70B-Instruct-Turbo"

# [provider]
# name = "openrouter"
# display_name = "OpenRouter"
# base_url = "https://openrouter.ai/api/v1"
# api_key_env = "OPENROUTER_API_KEY"
# models = ["deepseek/deepseek-chat-v3-0324"]
# default_model = "deepseek/deepseek-chat-v3-0324"

# [provider]
# name = "ollama"
# display_name = "Ollama (local)"
# base_url = "http://localhost:11434/v1"
# api_key = "ollama"      # Ollama doesn't need a real key
# models = ["qwen3:32b", "codellama:34b"]
# default_model = "qwen3:32b"

# [provider]
# name = "fireworks"
# display_name = "Fireworks AI"
# base_url = "https://api.fireworks.ai/inference/v1"
# api_key_env = "FIREWORKS_API_KEY"
# models = ["accounts/fireworks/models/llama4-maverick-instruct-basic"]
# default_model = "accounts/fireworks/models/llama4-maverick-instruct-basic"
"""
    target.write_text(content, encoding="utf-8")
    return target
