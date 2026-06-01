# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),

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
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
