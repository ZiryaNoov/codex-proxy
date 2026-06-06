# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [4.0.0] - 2026-06-07

### Fixed

- **`__main__.py`**: `--port 0` and `--host ""` no longer silently ignored (`is not None` check)
- **`store.py`**: Removed production `assert` that could silently crash with `-O` flag
- **`compaction.py`**: Compaction notice now says "dropped" instead of misleading "summarized"
- **`tui.py`**: Success rate now correct after first request (off-by-one fix)
- **`circuit_breaker.py`**: `get_status()` now includes `last_failure_time` field
- **`Dockerfile`**: Binds to `0.0.0.0` for container networking

### Changed

- Removed duplicate `_mask_key()` from `server.py` — single source in `key_rotation.py`
- `KeyRotator` now exposes `key_count` property (no more `_keys` access)
- `ResponseStore` now exposes `clear()` method (no more `_store` access)
- `server.py` no longer accesses private `_keys` on `KeyRotator`
- `tui.py` no longer accesses private `_store` on `ResponseStore`
- `tui.py` no longer shadows `state_colors` variable name
- Hardcoded `MAX_RETRIES`, `RETRY_DELAY`, httpx timeouts are now configurable via config
- Example config URL corrected to `ZiryaNoov/codex-proxy`

### Added

- **CORS middleware** — configurable via `cors_origins` in `[server]` config
- **Admin authentication** — optional Bearer token on `/reload` and `/status` endpoints
- **Rate limiting** — per-client sliding window rate limiter (`[rate_limit]` config section)
- **Request size limits** — configurable `max_request_body_bytes` (default 10MB)
- **Configurable timeouts** — `connect_timeout`, `read_timeout`, `max_retries`, `retry_delay`
- **Provider adapters** for Together AI and Fireworks AI (11 adapters total)
- **`rate_limiter.py`** — new module with `RateLimiter` class
- **217 tests** (up from 184) with new test files:
  - `test_rate_limiter.py` — rate limiter unit tests
  - `test_server_features.py` — rate limiting, admin auth, request size integration tests
  - `test_edge_cases.py` — compaction edge cases, config TOML, provider adapter registry
- `pyproject.toml` now includes `readme = "README.md"` for PyPI

## [3.1.0] - 2026-06-01

### Added
- Dynamic, unified configuration and service reloading across HTTP and TUI (`reload_config_internal`).
- Instant, non-blocking Unix/macOS keyboard input using `termios`/`tty` cbreak mode.

## [2.0.1] - 2026-05-31

### Fixed

- **Compaction config threading**: `max_messages` and `keep_last` from config.toml
  are now correctly passed to the compaction engine (were previously hardcoded)
- **Circuit breaker type annotation**: `AppState.circuit_breaker` now correctly
  typed as `CircuitBreaker | None`
- **Circuit breaker coverage**: Now protects streaming HTTP and WebSocket paths
  (was only protecting non-streaming HTTP)
- **Config reload**: `/reload` now recreates circuit breaker with new config values
- **Example config**: `codex-proxy --init` now generates `[circuit_breaker]` and
  `[compaction]` sections

### Added

- `--print-config` now shows circuit_breaker and compaction settings
- MIT `LICENSE` file

## [2.0.0] - 2026-05-31

### Added

- **6 new provider adapters** for broader LLM ecosystem support:
  - Anthropic — `x-api-key` header and `anthropic-version` handling
  - Gemini — Google's OpenAI-compatible endpoint
  - DeepSeek — stream_options stripping
  - Mistral — OpenAI-compatible with stream_options handling
  - Cohere — OpenAI-compatible endpoint
  - NVIDIA — NIM OpenAI-compatible endpoint
- **Circuit breaker** for upstream resilience — protects against failing providers
  with configurable failure threshold, recovery timeout, and half-open state
- **Context compaction** for long conversations — automatically trims message
  history to fit within limits while preserving system prompts and recent context
- **CI/CD pipeline** (GitHub Actions) — automated lint, test, and release workflows
- **Docker Compose** support — one-command containerized deployment with health checks
- **Pre-commit hooks** — Ruff linting and formatting on every commit
- **112+ tests** covering translator, config, store, server, providers, circuit
  breaker, and compaction modules
- **CONTRIBUTING.md** — development setup, code style, PR process, and commit conventions
- **CODE_OF_CONDUCT.md** — community guidelines
- **Issue templates** and **PR template** for structured contributions

## [1.0.0] - 2026-05-19

### Added

- Core **Responses API to Chat Completions** protocol translation
- **Streaming SSE** support with real-time token delivery
- **WebSocket** support with full Realtime API envelope handling
- **Reasoning/thinking token** passthrough from supported models
- **Tool calls** — full function calling support (definitions + results)
- **Multi-turn conversations** via `previous_response_id` with in-memory response store
- **Multi-provider** backend — switch between Z.AI, Groq, Together AI, OpenRouter,
  Ollama, Fireworks, and more with a single config change
- **Usage tracking** — captures token counts from streaming responses
- **Auto-retry** — one retry on 5xx/transport errors for non-streaming requests
- **TOML configuration** file with env var and CLI flag overrides
- **FastAPI** server with `/responses`, `/models`, `/health`, `/status`, and `/reload` endpoints
- **Dockerfile** for containerized deployment
- **CLI** with `--init`, `--print-config`, `--port`, `--host`, and `--config` options
