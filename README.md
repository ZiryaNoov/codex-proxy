# codex-proxy

[![CI](https://github.com/ZiryaNoov/codex-proxy/actions/workflows/ci.yml/badge.svg)](https://github.com/ZiryaNoov/codex-proxy/actions/workflows/ci.yml)
[![PyPI version](https://img.shields.io/pypi/v/codex-proxy.svg)](https://pypi.org/project/codex-proxy/)
[![Python version](https://img.shields.io/pypi/pyversions/codex-proxy.svg)](https://pypi.org/project/codex-proxy/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/ZiryaNoov/codex-proxy/blob/main/LICENSE)

**Lightweight LLM Gateway Platform — multi-provider proxy with smart routing, JWT auth, cost analytics, and web dashboard.**

Use Codex CLI with **any** Chat Completions-compatible provider -- Z.AI, Groq,
Together AI, OpenRouter, Ollama, Fireworks, Anthropic, Gemini, DeepSeek, Mistral,
Cohere, NVIDIA NIM, and more.

---

## Why codex-proxy?

| | codex-proxy | LiteLLM |
|---|---|---|
| **Install** | `pip install codex-proxy` | `pip install litellm[proxy]` |
| **Dependencies** | 6 (FastAPI, uvicorn, httpx, tomli, sqlalchemy, aiosqlite) | 50+ |
| **Config** | Single TOML file | YAML + env vars + DB |
| **Start time** | <1s | 3-5s |
| **Memory** | ~30MB | ~200MB+ |
| **Dashboard** | TUI + Web UI | Separate Admin UI |
| **Auth** | Built-in JWT | External |
| **Smart Routing** | 4 strategies | Basic |
| **Cost Tracking** | Per-model pricing + analytics | Via logging |
| **Circuit Breaker** | Per-key + global | Basic |
| **Plugins** | Built-in hook system | Callbacks only |

## Architecture

```
                          codex-proxy v5.0.0
 ┌────────────┐      ┌──────────────────────────────────┐      ┌──────────────────┐
 │            │      │                                  │      │                  │
 │  Codex CLI │─────>│     FastAPI server               │─────>│   LLM Provider   │
 │  Cursor    │      │     localhost:4242                │      │   (CC endpoint)  │
 │  Any IDE   │      │                                  │      │                  │
 │            │<─────│  Core:                           │<─────│  Z.AI / Groq /   │
 └────────────┘      │  . Translator                    │      │  Ollama / etc.   │
                     │  . Response Store                 │      └──────────────────┘
  Responses API      │  . Circuit Breaker                │
  protocol           │  . Key Rotator                    │      Chat Completions
                     │  . Compaction Engine               │      protocol
                     │  . Plugin Registry                 │
                     │  . Rate Limiter                    │      ┌──────────────────┐
                     │  . Provider Adapters (12+)         │      │  SQLite / PG DB  │
                     │                                   │─────>│                  │
                     │  v5 Gateway Features:              │      │  . Users         │
                     │  . Smart Router (4 strategies)     │      │  . API Keys      │
                     │  . JWT Auth (bcrypt + tokens)      │      │  . Providers     │
                     │  . Cost Tracking (25+ models)      │      │  . Request Logs  │
                     │  . Budget Enforcement              │      │  . Budgets       │
                     │  . Web Dashboard (/dashboard)      │      │  . Analytics     │
                     │  . Multi-Provider Routing          │      └──────────────────┘
                     └──────────────────────────────────┘
```

## Features

### Core

- **Protocol translation** -- Responses API to Chat Completions in real time
- **Streaming SSE** -- token-by-token delivery with full protocol mapping
- **WebSocket support** -- full Realtime API envelope handling
- **Reasoning passthrough** -- forwards thinking/reasoning tokens
- **Tool calls** -- full function calling support (definitions + results)
- **Multi-turn** -- `previous_response_id` via in-memory response store
- **Auto-retry** -- configurable retries on 5xx/transport errors
- **Rate limiting** -- per-client sliding window rate limiter
- **Admin auth** -- optional Bearer token on `/reload` and `/status` endpoints
- **CORS support** -- configurable allowed origins
- **Request size limits** -- configurable max body size (default 10MB)

### v5 Gateway Features

- **Multi-provider support** -- route to multiple providers via `[[providers]]` config
- **Smart routing** -- 4 strategies: `fallback`, `cost` (cheapest), `latency` (fastest), `weighted` (load balanced)
- **JWT authentication** -- login/signup/refresh tokens with bcrypt password hashing
- **Cost tracking** -- per-model pricing with automatic cost calculation on every request
- **Budget enforcement** -- set daily/monthly spend limits per user; requests blocked when exceeded
- **Web dashboard** -- dark-themed HTML dashboard at `/dashboard` with live stats, cost charts, provider cards
- **Database layer** -- async SQLAlchemy (SQLite or PostgreSQL) with 13 tables, migrations, and CRUD
- **25+ model prices** -- built-in pricing data for GLM, GPT, Claude, Gemini, DeepSeek, Llama, and more

### Reliability

- **Circuit breaker** -- global fail-fast when upstream is down (configurable threshold + recovery)
- **Multi-key rotation** -- round-robin across API keys with **per-key circuit breakers**; auth/rate-limit errors (401/403/429) trip individual keys
- **Context compaction** -- auto-trims long conversations to stay within model limits

### Observability

- **Live TUI dashboard** -- real-time metrics, circuit breaker state, key pool status, log tail, hotkeys
- **Web dashboard** -- browser-based dashboard with auto-refresh, cost breakdown, provider status, router metrics
- **Plugin system** -- hook-based middleware (`on_request`, `on_response`, `on_error`, `on_startup`, `on_shutdown`)
- **Config hot-reload** -- reload config without restart via TUI hotkey or `POST /reload`

### Ecosystem

- **12+ providers** -- Z.AI, Groq, Together, OpenRouter, Ollama, Fireworks, Anthropic, Gemini, DeepSeek, Mistral, Cohere, NVIDIA NIM
- **Provider adapters** -- per-provider header/request normalization
- **Docker-ready** -- Dockerfile and Compose file included
- **pip-installable** -- `pip install codex-proxy`, run with `codex-proxy` CLI
- **270+ tests** -- comprehensive test suite covering all modules

## Quick Start

### Install

```bash
pip install codex-proxy
```

With extras:

```bash
pip install "codex-proxy[tui]"          # Terminal dashboard
pip install "codex-proxy[postgres]"     # PostgreSQL backend
pip install "codex-proxy[enterprise]"   # bcrypt + JWT + crypto + PG
```

### Configure

```bash
codex-proxy --init
# Edit ~/.codex-proxy/config.toml with your provider details
```

### Run

```bash
# Standard mode (v4 compatible)
codex-proxy

# With live TUI dashboard
codex-proxy --tui
```

### Enable v5 Features

Add to your `~/.codex-proxy/config.toml`:

```toml
# Enable persistent database
[database]
enabled = true
# url = ""  # empty = SQLite at ~/.codex-proxy/proxy.db

# Enable JWT authentication
[auth]
enabled = true
secret_key = "your-secret-key-here"  # auto-generated if empty
admin_username = "admin"
admin_password = "changeme"  # hashed on first startup

# Enable smart routing (use with [[providers]])
[router]
enabled = true
default_strategy = "fallback"  # cost|latency|fallback|weighted

# Enable web dashboard
[dashboard]
enabled = true
```

### Multi-Provider Setup

```toml
[[providers]]
name = "zai"
display_name = "Z.AI"
base_url = "https://api.z.ai/api/paas/v4"
api_key_env = "OPENAI_API_KEY"
models = ["glm-5.1", "glm-5", "glm-4.7"]
default_model = "glm-5.1"

[[providers]]
name = "groq"
display_name = "Groq"
base_url = "https://api.groq.com/openai/v1"
api_key_env = "GROQ_API_KEY"
models = ["llama-4-maverick-17b"]
default_model = "llama-4-maverick-17b"
```

### Connect Codex CLI

```bash
export OPENAI_BASE_URL=http://127.0.0.1:4242
codex --model glm-5.1 "say hello"
```

## v5 API Endpoints

### Auth

| Endpoint | Method | Description |
|---|---|---|
| `/auth/login` | POST | Authenticate user, returns JWT tokens |
| `/auth/signup` | POST | Register new user (admin-only, or first user auto-admin) |
| `/auth/refresh` | POST | Refresh access token |
| `/auth/me` | GET | Get current user info |
| `/auth/budget` | GET | Get current user's budget status |
| `/auth/budget` | PUT | Set or update budget limits |

### Dashboard & Analytics

| Endpoint | Method | Description |
|---|---|---|
| `/dashboard` | GET | Web dashboard (HTML) |
| `/api/stats` | GET | Aggregated stats: requests, costs, per-model breakdown |
| `/api/usage` | GET | Cost/token usage (`?model=` filter, `?hours=` period) |
| `/api/providers` | GET | Provider status with routing info |
| `/api/router/status` | GET | Detailed smart router metrics |

### Core

| Endpoint | Method | Description |
|---|---|---|
| `/responses` | POST | Responses API (HTTP, streaming + non-streaming) |
| `/responses` | WS | Responses API (WebSocket) |
| `/responses/{id}` | GET | Retrieve a stored response |
| `/models` | GET | List all models across providers |
| `/v1/models` | GET | List models (v1 prefix alias) |
| `/health` | GET | Health check (`?check_backend=true` pings upstream) |
| `/status` | GET | Detailed server status |
| `/reload` | POST | Reload config from disk |

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

## Multi-Key Rotation

```toml
[provider]
name = "zai"
base_url = "https://api.z.ai/api/paas/v4"
api_keys = ["sk-key1", "sk-key2", "sk-key3"]
models = ["glm-5.1"]
default_model = "glm-5.1"
```

Each key gets its own circuit breaker. Auth errors (401/403/429) trip the
individual key; server errors (5xx) are handled by the global circuit breaker.

## Plugin System

```toml
[plugins]
enabled = true
plugins = [
    "codex_proxy.plugins_builtin.LoggingPlugin",
]
```

```python
from codex_proxy.plugins import Plugin, PluginContext

class MyPlugin(Plugin):
    async def on_request(self, ctx: PluginContext) -> None:
        pass

    async def on_response(self, ctx: PluginContext) -> None:
        pass

    async def on_error(self, ctx: PluginContext) -> None:
        pass
```

## Configuration Reference

Config file: `~/.codex-proxy/config.toml`

### `[server]`

| Field | Type | Default | Description |
|---|---|---|---|
| `host` | string | `"127.0.0.1"` | Bind address |
| `port` | int | `4242` | Bind port |
| `log_level` | string | `"warning"` | Log verbosity |
| `max_retries` | int | `1` | Retries on 5xx/transport errors |
| `connect_timeout` | float | `10.0` | Seconds to connect to upstream |
| `read_timeout` | float | `180.0` | Seconds to wait for upstream response |
| `admin_token` | string | `""` | Bearer token for admin endpoints |
| `max_request_body_bytes` | int | `10485760` | Max request body size (10MB) |
| `cors_origins` | list | `[]` | Allowed CORS origins |

### `[database]` (v5)

| Field | Type | Default | Description |
|---|---|---|---|
| `enabled` | bool | `false` | Enable persistent storage |
| `url` | string | `""` | DB URL (empty = SQLite at `~/.codex-proxy/proxy.db`) |
| `echo` | bool | `false` | SQL debug logging |

### `[auth]` (v5)

| Field | Type | Default | Description |
|---|---|---|---|
| `enabled` | bool | `false` | Enable JWT authentication |
| `secret_key` | string | `""` | JWT signing key (auto-generated if empty) |
| `access_token_expire_minutes` | int | `15` | Access token lifetime |
| `refresh_token_expire_days` | int | `7` | Refresh token lifetime |
| `admin_username` | string | `"admin"` | Admin username (seeded on first startup) |
| `admin_password` | string | `""` | Admin password (default: `changeme`) |

### `[router]` (v5)

| Field | Type | Default | Description |
|---|---|---|---|
| `enabled` | bool | `false` | Enable smart routing |
| `default_strategy` | string | `"fallback"` | Strategy: `cost`, `latency`, `fallback`, `weighted` |

### `[dashboard]` (v5)

| Field | Type | Default | Description |
|---|---|---|---|
| `enabled` | bool | `false` | Serve web dashboard at `/dashboard` |
| `open_browser` | bool | `false` | Auto-open browser on startup |

### `[provider]`

| Field | Type | Default | Description |
|---|---|---|---|
| `name` | string | `"zai"` | Provider identifier |
| `display_name` | string | `"Z.AI"` | Human-readable name |
| `base_url` | string | Provider endpoint | Chat Completions URL |
| `api_key` | string | `""` | API key (inline) |
| `api_key_env` | string | `""` | Env var for API key |
| `api_keys` | list | `[]` | Multiple keys for rotation |
| `models` | list | `["glm-5.1", ...]` | Available model IDs |
| `default_model` | string | `"glm-5.1"` | Default model |

### `[circuit_breaker]`

| Field | Type | Default | Description |
|---|---|---|---|
| `enabled` | bool | `true` | Enable/disable |
| `failure_threshold` | int | `5` | Failures before opening |
| `recovery_timeout` | float | `30.0` | Seconds before half-open |

### `[compaction]`

| Field | Type | Default | Description |
|---|---|---|---|
| `enabled` | bool | `true` | Enable/disable |
| `max_messages` | int | `50` | Threshold to trigger |
| `keep_last` | int | `20` | Recent messages to keep |

## Docker

```bash
docker build -t codex-proxy .
docker run -d -p 4242:4242 \
  -e CODEX_PROXY_API_KEY=your-key \
  -e CODEX_PROXY_BASE_URL=https://api.z.ai/api/paas/v4 \
  codex-proxy
```

## Development

```bash
git clone https://github.com/ZiryaNoov/codex-proxy.git
cd codex-proxy
pip install -e ".[dev,tui]"
pytest tests/ -v    # 270+ tests
```

## License

[MIT](https://github.com/ZiryaNoov/codex-proxy/blob/main/LICENSE) -- ZakPro
