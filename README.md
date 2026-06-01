# codex-proxy

[![CI](https://github.com/ZiryaNoov/codex-proxy/actions/workflows/ci.yml/badge.svg)](https://github.com/ZiryaNoov/codex-proxy/actions/workflows/ci.yml)
[![PyPI version](https://img.shields.io/pypi/v/codex-proxy.svg)](https://pypi.org/project/codex-proxy/)
[![Python version](https://img.shields.io/pypi/pyversions/codex-proxy.svg)](https://pypi.org/project/codex-proxy/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/ZiryaNoov/codex-proxy/blob/main/LICENSE)

**Responses API to Chat Completions bridge for OpenAI Codex CLI.**

Use Codex CLI with **any** Chat Completions-compatible provider -- Z.AI, Groq,
Together AI, OpenRouter, Ollama, Fireworks, Anthropic, Gemini, DeepSeek, Mistral,
Cohere, NVIDIA NIM, and more.

---

## Why codex-proxy?

| | codex-proxy | LiteLLM |
|---|---|---|
| **Install** | `pip install codex-proxy` | `pip install litellm[proxy]` |
| **Dependencies** | 4 (FastAPI, uvicorn, httpx, tomli) | 50+ |
| **Config** | Single TOML file | YAML + env vars + DB |
| **Start time** | <1s | 3-5s |
| **Memory** | ~30MB | ~200MB+ |
| **Dashboard** | Built-in TUI (terminal) | Separate Admin UI |
| **Circuit Breaker** | Per-key + global | Basic |
| **Plugins** | Built-in hook system | Callbacks only |

If you need 100+ providers and enterprise features, use LiteLLM.
If you need a **lightweight, reliable proxy** with advanced resilience features
and a live dashboard, codex-proxy is for you.

## Architecture

```
                      codex-proxy v3.1.0
 ┌────────────┐      ┌──────────────────────────┐      ┌──────────────────┐
 │            │      │                          │      │                  │
 │  Codex CLI │─────>│    FastAPI server        │─────>│   LLM Provider   │
 │  Cursor    │      │    localhost:4242         │      │   (CC endpoint)  │
 │  Any IDE   │      │                          │      │                  │
 │            │<─────│  . Translator             │<─────│  Z.AI / Groq /   │
 └────────────┘      │  . Response Store         │      │  Ollama / etc.   │
                     │  . Circuit Breaker        │      └──────────────────┘
  Responses API      │  . Key Rotator            │
  protocol           │  . Compaction Engine       │      Chat Completions
                     │  . Plugin Registry         │      protocol
                     │  . Provider Adapters       │
                     └──────────────────────────┘
```

## Features

### Core

- **Protocol translation** -- Responses API to Chat Completions in real time
- **Streaming SSE** -- token-by-token delivery with full protocol mapping
- **WebSocket support** -- full Realtime API envelope handling
- **Reasoning passthrough** -- forwards thinking/reasoning tokens
- **Tool calls** -- full function calling support (definitions + results)
- **Multi-turn** -- `previous_response_id` via in-memory response store
- **Auto-retry** -- one retry on 5xx/transport errors

### Reliability

- **Circuit breaker** -- global fail-fast when upstream is down (configurable threshold + recovery)
- **Multi-key rotation** -- round-robin across API keys with **per-key circuit breakers**; auth/rate-limit errors (401/403/429) trip individual keys; 5xx handled by global breaker
- **Context compaction** -- auto-trims long conversations to stay within model limits

### Observability

- **Live TUI dashboard** -- real-time metrics, circuit breaker state, key pool status, log tail, hotkeys (`r` reload, `c` clear store, `t` compact, `q` quit)
- **Plugin system** -- hook-based middleware (`on_request`, `on_response`, `on_error`, `on_startup`, `on_shutdown`) with built-in `LoggingPlugin`
- **Config hot-reload** -- reload config without restart via TUI hotkey or `POST /reload`

### Ecosystem

- **12+ providers** -- Z.AI, Groq, Together, OpenRouter, Ollama, Fireworks, Anthropic, Gemini, DeepSeek, Mistral, Cohere, NVIDIA NIM
- **Provider adapters** -- per-provider header/request normalization
- **Docker-ready** -- Dockerfile and Compose file included
- **pip-installable** -- `pip install codex-proxy`, run with `codex-proxy` CLI
- **184+ tests** -- comprehensive test suite covering all modules

## Quick Start

### Install

```bash
pip install codex-proxy
```

For the TUI dashboard:

```bash
pip install "codex-proxy[tui]"
```

### Configure

```bash
codex-proxy --init
# Edit ~/.codex-proxy/config.toml with your provider details
```

### Run

```bash
# Standard mode
codex-proxy

# With live dashboard
codex-proxy --tui
```

### Connect Codex CLI

Set the environment variable:

```bash
export OPENAI_BASE_URL=http://127.0.0.1:4242
```

Or edit `~/.codex/config.toml`:

```toml
model = "glm-5.1"
```

And set your API key in `~/.codex/auth.json`:

```json
{
  "auth_mode": "apikey",
  "OPENAI_API_KEY": "your-provider-api-key"
}
```

Then run:

```bash
codex --model glm-5.1 "say hello"
```

## TUI Dashboard

Launch with `codex-proxy --tui` to see a live dashboard:

![codex-proxy TUI Dashboard](assets/tui-dashboard.png)

Hotkeys: `r` reload config, `c` clear store, `t` show compaction info, `q` quit.

## Provider Examples

### Z.AI (GLM Models)

```toml
[provider]
name = "zai"
display_name = "Z.AI"
base_url = "https://api.z.ai/api/paas/v4"
api_key_env = "OPENAI_API_KEY"
models = ["glm-5.1", "glm-5", "glm-4.7"]
default_model = "glm-5.1"
```

### Groq

```toml
[provider]
name = "groq"
display_name = "Groq"
base_url = "https://api.groq.com/openai/v1"
api_key_env = "GROQ_API_KEY"
models = ["llama-4-maverick-17b", "mixtral-8x7b-32768"]
default_model = "llama-4-maverick-17b"
```

### Together AI

```toml
[provider]
name = "together"
display_name = "Together AI"
base_url = "https://api.together.xyz/v1"
api_key_env = "TOGETHER_API_KEY"
models = ["meta-llama/Llama-3.3-70B-Instruct-Turbo"]
default_model = "meta-llama/Llama-3.3-70B-Instruct-Turbo"
```

### OpenRouter

```toml
[provider]
name = "openrouter"
display_name = "OpenRouter"
base_url = "https://openrouter.ai/api/v1"
api_key_env = "OPENROUTER_API_KEY"
models = ["deepseek/deepseek-chat-v3-0324"]
default_model = "deepseek/deepseek-chat-v3-0324"
```

### Ollama (Local)

```toml
[provider]
name = "ollama"
display_name = "Ollama (local)"
base_url = "http://localhost:11434/v1"
api_key = "ollama"
models = ["qwen3:32b", "codellama:34b"]
default_model = "qwen3:32b"
```

### Anthropic

```toml
[provider]
name = "anthropic"
display_name = "Anthropic"
base_url = "https://api.anthropic.com/v1"
api_key_env = "ANTHROPIC_API_KEY"
models = ["claude-sonnet-4-20250514"]
default_model = "claude-sonnet-4-20250514"
```

### Google Gemini

```toml
[provider]
name = "gemini"
display_name = "Google Gemini"
base_url = "https://generativelanguage.googleapis.com/v1beta/openai"
api_key_env = "GEMINI_API_KEY"
models = ["gemini-2.5-flash"]
default_model = "gemini-2.5-flash"
```

### DeepSeek

```toml
[provider]
name = "deepseek"
display_name = "DeepSeek"
base_url = "https://api.deepseek.com/v1"
api_key_env = "DEEPSEEK_API_KEY"
models = ["deepseek-chat", "deepseek-reasoner"]
default_model = "deepseek-chat"
```

### Mistral AI

```toml
[provider]
name = "mistral"
display_name = "Mistral AI"
base_url = "https://api.mistral.ai/v1"
api_key_env = "MISTRAL_API_KEY"
models = ["mistral-large-latest"]
default_model = "mistral-large-latest"
```

### Cohere

```toml
[provider]
name = "cohere"
display_name = "Cohere"
base_url = "https://api.cohere.com/compatibility/v1"
api_key_env = "CO_API_KEY"
models = ["command-a-03-2025"]
default_model = "command-a-03-2025"
```

### NVIDIA NIM

```toml
[provider]
name = "nvidia"
display_name = "NVIDIA NIM"
base_url = "https://integrate.api.nvidia.com/v1"
api_key_env = "NVIDIA_API_KEY"
models = ["nvidia/llama-3.1-nemotron-ultra-253b-v1"]
default_model = "nvidia/llama-3.1-nemotron-ultra-253b-v1"
```

### Fireworks AI

```toml
[provider]
name = "fireworks"
display_name = "Fireworks AI"
base_url = "https://api.fireworks.ai/inference/v1"
api_key_env = "FIREWORKS_API_KEY"
models = ["accounts/fireworks/models/llama4-maverick-instruct-basic"]
default_model = "accounts/fireworks/models/llama4-maverick-instruct-basic"
```

## Multi-Key Rotation

Distribute load across multiple API keys with automatic failover:

```toml
[provider]
name = "zai"
base_url = "https://api.z.ai/api/paas/v4"
api_keys = ["sk-key1", "sk-key2", "sk-key3"]
# or load from env vars:
# api_keys_env = ["OPENAI_API_KEY_1", "OPENAI_API_KEY_2"]
models = ["glm-5.1"]
default_model = "glm-5.1"
```

Each key gets its own circuit breaker. Auth errors (401/403/429) trip the
individual key; server errors (5xx) are handled by the global circuit breaker.
When a key's circuit opens, it's skipped until recovery. If all keys are open,
the first key is used as fallback.

## Plugin System

Extend codex-proxy with custom middleware:

```toml
[plugins]
enabled = true
plugins = [
    "codex_proxy.plugins_builtin.LoggingPlugin",
]
```

Plugins implement async hooks:

```python
from codex_proxy.plugins import Plugin, PluginContext

class MyPlugin(Plugin):
    async def on_request(self, ctx: PluginContext) -> None:
        # Called before forwarding to provider
        pass

    async def on_response(self, ctx: PluginContext) -> None:
        # Called after successful response
        pass

    async def on_error(self, ctx: PluginContext) -> None:
        # Called on failure
        pass
```

Broken plugins are isolated -- they cannot crash the proxy.

## Configuration Reference

Config file: `~/.codex-proxy/config.toml`

### `[server]`

| Field | Type | Default | Description |
|---|---|---|---|
| `host` | string | `"127.0.0.1"` | Bind address |
| `port` | int | `4242` | Bind port |
| `log_level` | string | `"warning"` | Log verbosity: `debug`, `info`, `warning`, `error` |
| `log_dir` | string | `~/.codex-proxy/logs` | Directory for debug log files |

### `[store]`

| Field | Type | Default | Description |
|---|---|---|---|
| `ttl_seconds` | int | `600` | Response cache TTL in seconds (10 min) |
| `max_entries` | int | `100` | Maximum cached responses for `previous_response_id` |

### `[provider]`

| Field | Type | Default | Description |
|---|---|---|---|
| `name` | string | `"zai"` | Provider identifier (used for adapter selection) |
| `display_name` | string | `"Z.AI"` | Human-readable provider name |
| `base_url` | string | `"https://api.z.ai/api/paas/v4"` | Provider Chat Completions endpoint |
| `api_key` | string | `""` | API key (inline) |
| `api_key_env` | string | `""` | Environment variable name for the API key |
| `api_keys` | list | `[]` | Multiple API keys for rotation |
| `api_keys_env` | list | `[]` | Env var names for multiple API keys |
| `models` | list | `["glm-5.1", ...]` | Available model IDs |
| `default_model` | string | `"glm-5.1"` | Default model when none specified |
| `stream` | bool | `true` | Enable streaming by default |
| `extra_headers` | dict | `{}` | Additional HTTP headers per request |

### `[circuit_breaker]`

| Field | Type | Default | Description |
|---|---|---|---|
| `enabled` | bool | `true` | Enable/disable circuit breaker |
| `failure_threshold` | int | `5` | Consecutive failures before opening |
| `recovery_timeout` | float | `30.0` | Seconds before half-open retry |

### `[compaction]`

| Field | Type | Default | Description |
|---|---|---|---|
| `enabled` | bool | `true` | Enable/disable context compaction |
| `max_messages` | int | `50` | Message count threshold to trigger compaction |
| `keep_last` | int | `20` | Number of recent messages to preserve |

### `[plugins]`

| Field | Type | Default | Description |
|---|---|---|---|
| `enabled` | bool | `false` | Enable/disable plugin system |
| `plugins` | list | `[]` | Dotted paths to plugin classes |

## Environment Variables

| Variable | Description |
|---|---|
| `CODEX_PROXY_API_KEY` | API key for the provider (highest priority) |
| `CODEX_PROXY_BASE_URL` | Override provider base URL |
| `CODEX_PROXY_MODEL` | Override default model name |
| `OPENAI_API_KEY` | Fallback API key when no config file exists |
| `OPENAI_BASE_URL` | Point Codex CLI to the proxy (`http://127.0.0.1:4242`) |

Environment variables are used when `~/.codex-proxy/config.toml` does not exist,
enabling zero-config deployment via env vars alone.

## Docker

### Build and Run

```bash
docker build -t codex-proxy .
docker run -d \
  -p 4242:4242 \
  -e CODEX_PROXY_API_KEY=your-key \
  -e CODEX_PROXY_BASE_URL=https://api.z.ai/api/paas/v4 \
  -e CODEX_PROXY_MODEL=glm-5.1 \
  codex-proxy
```

### Docker Compose

```bash
# Set your API key
export CODEX_PROXY_API_KEY=your-key

# Start the proxy
docker compose up -d

# Check health
curl http://localhost:4242/health
```

The Compose file includes a health check that polls `/health` every 30 seconds.

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/responses` | POST | Responses API (HTTP, streaming + non-streaming) |
| `/responses` | WS | Responses API (WebSocket, full envelope handling) |
| `/responses/{id}` | GET | Retrieve a stored response by ID |
| `/models` | GET | List available models |
| `/v1/models` | GET | List available models (v1 prefix alias) |
| `/health` | GET | Health check (`?check_backend=true` pings upstream) |
| `/status` | GET | Detailed server status (uptime, requests, provider info) |
| `/reload` | POST | Reload configuration from disk without restart |

## CLI Options

```
codex-proxy                  Start the proxy server
codex-proxy --tui            Start with live TUI dashboard
codex-proxy --port 8080      Override bind port
codex-proxy --host 0.0.0.0   Override bind address
codex-proxy --config PATH    Use custom config file
codex-proxy --init           Write example config and exit
codex-proxy --print-config   Print resolved config and exit
```

## Development

### Setup

```bash
git clone https://github.com/ZiryaNoov/codex-proxy.git
cd codex-proxy
pip install -e ".[dev,tui]"
```

### Testing

```bash
pytest tests/ -v    # 184+ tests
```

### Linting & Type Checking

```bash
ruff check src/ tests/
mypy src/
```

### Pre-commit Hooks

```bash
pre-commit install
```

## Contributing

Contributions are welcome! Please read the
[Contributing Guide](CONTRIBUTING.md) and
[Code of Conduct](CODE_OF_CONDUCT.md).

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

[MIT](https://github.com/ZiryaNoov/codex-proxy/blob/main/LICENSE) -- ZakPro
