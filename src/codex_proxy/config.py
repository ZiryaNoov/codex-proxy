"""Config file loading — ~/.codex-proxy/config.toml"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore[import-not-found]

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
    api_keys: list[str] = field(default_factory=list)
    api_keys_env: list[str] = field(default_factory=list)
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

    def effective_api_keys(self) -> list[str]:
        """Return the full resolved key pool."""
        keys: list[str] = []
        if self.api_keys:
            keys.extend(self.api_keys)
        for env_name in self.api_keys_env:
            val = os.environ.get(env_name, "")
            if val:
                keys.append(val)
        if not keys:
            single = self.effective_api_key()
            if single:
                keys.append(single)
        return keys


@dataclass
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = DEFAULT_PORT
    log_level: str = "warning"
    log_dir: Path = field(default_factory=lambda: DEFAULT_DIR / "logs")
    max_retries: int = 1
    retry_delay: float = 0.5
    connect_timeout: float = 10.0
    read_timeout: float = 180.0
    admin_token: str = ""
    max_request_body_bytes: int = 10 * 1024 * 1024  # 10 MB
    cors_origins: list[str] = field(default_factory=list)


@dataclass
class StoreConfig:
    ttl_seconds: int = 600
    max_entries: int = 100


@dataclass
class CircuitBreakerConfig:
    enabled: bool = True
    failure_threshold: int = 5
    recovery_timeout: float = 30.0


@dataclass
class CompactionConfig:
    enabled: bool = True
    max_messages: int = 50
    keep_last: int = 20


@dataclass
class PluginConfig:
    enabled: bool = False
    plugins: list[str] = field(default_factory=list)


@dataclass
class RateLimitConfig:
    enabled: bool = False
    max_requests: int = 60
    window_seconds: int = 60


@dataclass
class ProxyConfig:
    server: ServerConfig = field(default_factory=ServerConfig)
    provider: ProviderConfig = field(default_factory=ProviderConfig)
    store: StoreConfig = field(default_factory=StoreConfig)
    circuit_breaker: CircuitBreakerConfig = field(default_factory=CircuitBreakerConfig)
    compaction: CompactionConfig = field(default_factory=CompactionConfig)
    plugins: PluginConfig = field(default_factory=PluginConfig)
    rate_limit: RateLimitConfig = field(default_factory=RateLimitConfig)


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
    store_raw = raw.get("store", {})
    cb_raw = raw.get("circuit_breaker", {})
    comp_raw = raw.get("compaction", {})
    plugins_raw = raw.get("plugins", {})

    server = ServerConfig(
        host=server_raw.get("host", "127.0.0.1"),
        port=server_raw.get("port", DEFAULT_PORT),
        log_level=server_raw.get("log_level", "warning"),
        log_dir=Path(server_raw.get("log_dir", str(DEFAULT_DIR / "logs"))),
        max_retries=server_raw.get("max_retries", 1),
        retry_delay=server_raw.get("retry_delay", 0.5),
        connect_timeout=server_raw.get("connect_timeout", 10.0),
        read_timeout=server_raw.get("read_timeout", 180.0),
        admin_token=server_raw.get("admin_token", ""),
        max_request_body_bytes=server_raw.get("max_request_body_bytes", 10 * 1024 * 1024),
        cors_origins=server_raw.get("cors_origins", []),
    )

    provider = ProviderConfig(
        name=provider_raw.get("name", "zai"),
        display_name=provider_raw.get("display_name", "Z.AI"),
        base_url=provider_raw.get("base_url", "https://api.z.ai/api/paas/v4"),
        api_key=provider_raw.get("api_key", ""),
        api_key_env=provider_raw.get("api_key_env", ""),
        api_keys=provider_raw.get("api_keys", []),
        api_keys_env=provider_raw.get("api_keys_env", []),
        models=provider_raw.get("models", ["glm-5.1", "glm-5", "glm-4.7"]),
        default_model=provider_raw.get("default_model", "glm-5.1"),
        stream=provider_raw.get("stream", True),
        extra_headers=provider_raw.get("extra_headers", {}),
    )

    store = StoreConfig(
        ttl_seconds=store_raw.get("ttl_seconds", 600),
        max_entries=store_raw.get("max_entries", 100),
    )

    circuit_breaker = CircuitBreakerConfig(
        enabled=cb_raw.get("enabled", True),
        failure_threshold=cb_raw.get("failure_threshold", 5),
        recovery_timeout=cb_raw.get("recovery_timeout", 30.0),
    )

    compaction = CompactionConfig(
        enabled=comp_raw.get("enabled", True),
        max_messages=comp_raw.get("max_messages", 50),
        keep_last=comp_raw.get("keep_last", 20),
    )

    plugins = PluginConfig(
        enabled=plugins_raw.get("enabled", False),
        plugins=plugins_raw.get("plugins", []),
    )

    rl_raw = raw.get("rate_limit", {})
    rate_limit = RateLimitConfig(
        enabled=rl_raw.get("enabled", False),
        max_requests=rl_raw.get("max_requests", 60),
        window_seconds=rl_raw.get("window_seconds", 60),
    )

    return ProxyConfig(
        server=server, provider=provider, store=store,
        circuit_breaker=circuit_breaker, compaction=compaction,
        plugins=plugins, rate_limit=rate_limit,
    )


def write_example_config(path: Path | None = None) -> Path:
    """Write an example config file."""
    target = path or DEFAULT_CONFIG
    target.parent.mkdir(parents=True, exist_ok=True)

    content = """\
# codex-proxy config — https://github.com/ZiryaNoov/codex-proxy

[server]
host = "127.0.0.1"
port = 4242
log_level = "warning"    # debug, info, warning, error
# max_retries = 1         # retries on 5xx/transport errors
# retry_delay = 0.5       # seconds between retries
# connect_timeout = 10.0  # seconds to connect to upstream
# read_timeout = 180.0    # seconds to wait for upstream response
# admin_token = ""        # if set, /reload and /status require Bearer token
# max_request_body_bytes = 10485760  # 10 MB max request body
# cors_origins = ["*"]    # allowed CORS origins (empty = no CORS)

[store]
ttl_seconds = 600         # response cache TTL (10 min)
max_entries = 100         # max cached responses

[circuit_breaker]
enabled = true             # protect upstream from cascading failures
failure_threshold = 5      # consecutive failures before opening circuit
recovery_timeout = 30.0    # seconds before trying half-open recovery

[compaction]
enabled = true             # auto-trim long conversations
max_messages = 50          # trigger compaction above this count
keep_last = 20             # recent messages to preserve

[rate_limit]
enabled = false            # per-client request throttling
max_requests = 60          # max requests per window
window_seconds = 60        # sliding window duration

[plugins]
enabled = true             # enable hook-based middleware plugins
plugins = [
    "codex_proxy.plugins_builtin.LoggingPlugin",  # built-in structured logger
]

[provider]
# Provider: Z.AI (GLM models)
name = "zai"
display_name = "Z.AI"
base_url = "https://api.z.ai/api/paas/v4"
api_key = ""             # or set api_key_env below
api_key_env = "OPENAI_API_KEY"  # reads from env var
# api_keys = ["sk-key1", "sk-key2", "sk-key3"]  # multi-key rotation
# api_keys_env = ["OPENAI_API_KEY_1", "OPENAI_API_KEY_2"]
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

# [provider]
# name = "anthropic"
# display_name = "Anthropic"
# base_url = "https://api.anthropic.com/v1"
# api_key_env = "ANTHROPIC_API_KEY"
# models = ["claude-sonnet-4-20250514"]
# default_model = "claude-sonnet-4-20250514"

# [provider]
# name = "gemini"
# display_name = "Google Gemini"
# base_url = "https://generativelanguage.googleapis.com/v1beta/openai"
# api_key_env = "GEMINI_API_KEY"
# models = ["gemini-2.5-flash"]
# default_model = "gemini-2.5-flash"

# [provider]
# name = "deepseek"
# display_name = "DeepSeek"
# base_url = "https://api.deepseek.com/v1"
# api_key_env = "DEEPSEEK_API_KEY"
# models = ["deepseek-chat", "deepseek-reasoner"]
# default_model = "deepseek-chat"

# [provider]
# name = "mistral"
# display_name = "Mistral AI"
# base_url = "https://api.mistral.ai/v1"
# api_key_env = "MISTRAL_API_KEY"
# models = ["mistral-large-latest"]
# default_model = "mistral-large-latest"

# [provider]
# name = "cohere"
# display_name = "Cohere"
# base_url = "https://api.cohere.com/compatibility/v1"
# api_key_env = "CO_API_KEY"
# models = ["command-a-03-2025"]
# default_model = "command-a-03-2025"

# [provider]
# name = "nvidia"
# display_name = "NVIDIA NIM"
# base_url = "https://integrate.api.nvidia.com/v1"
# api_key_env = "NVIDIA_API_KEY"
# models = ["nvidia/llama-3.1-nemotron-ultra-253b-v1"]
# default_model = "nvidia/llama-3.1-nemotron-ultra-253b-v1"
"""
    target.write_text(content, encoding="utf-8")
    return target
