# Contributing to codex-proxy

Thanks for your interest in contributing! This guide covers everything you need to get started.

## Development Setup

1. **Fork** the repository on GitHub
2. **Clone** your fork locally:
   ```bash
   git clone https://github.com/YOUR_USERNAME/codex-proxy.git
   cd codex-proxy
   ```
3. **Install** in editable mode with dev dependencies:
   ```bash
   pip install -e ".[dev]"
   ```
4. **Install pre-commit hooks** (optional but recommended):
   ```bash
   pre-commit install
   ```

## Code Style

- **Formatter & Linter**: [Ruff](https://docs.astral.sh/ruff/) — configuration lives in `pyproject.toml`
- **Target**: Python 3.10+
- **Line length**: 100 characters (E501 is ignored)
- **Type hints**: Encouraged on public APIs; `mypy` is available for checking
- **Data structures**: Use `@dataclass` for structured data (see `circuit_breaker.py` for reference)
- **Imports**: Sorted with isort via Ruff; first-party imports use `codex_proxy`

### Running the linter

```bash
ruff check src/ tests/
ruff format src/ tests/
```

### Type checking

```bash
mypy src/
```

## Running Tests

```bash
# Run full suite
pytest tests/ -v

# Run a specific test file
pytest tests/test_translator.py -v

# Run with coverage
pytest tests/ -v --tb=short
```

The test suite uses **pytest** with 112+ tests covering the translator, config, store, server, providers, circuit breaker, and compaction modules.

## Project Structure

```
codex-proxy/
  src/codex_proxy/       # Main package
    __init__.py          # Package init
    __main__.py          # CLI entry point
    server.py            # FastAPI app + endpoints
    translator.py        # Responses API <-> Chat Completions
    config.py            # TOML config loading
    store.py             # In-memory response store
    providers.py         # Provider-specific adapters
    circuit_breaker.py   # Upstream resilience
    compaction.py        # Context compaction
  tests/                 # Test suite
  .github/workflows/     # CI/CD pipelines
```

## Pull Request Process

1. **Create a branch** from `main`:
   ```bash
   git checkout -b feat/your-feature-name
   ```
2. **Make your changes** and add tests for new functionality
3. **Run checks** before pushing:
   ```bash
   ruff check src/ tests/
   pytest tests/ -v
   ```
4. **Push** to your fork:
   ```bash
   git push origin feat/your-feature-name
   ```
5. **Open a Pull Request** against the `main` branch

### PR Guidelines

- Keep PRs focused — one feature or fix per PR
- Add tests for any new behavior
- Update `README.md` if you change user-facing functionality
- All CI checks must pass (lint + tests)

## Commit Messages

Use [Conventional Commits](https://www.conventionalcommits.org/) style:

```
feat: add streaming retry with exponential backoff
fix: correct WebSocket close frame handling
refactor: extract shared streaming core
test: add circuit breaker edge case tests
docs: update provider configuration examples
chore: bump ruff to v0.9
```

**Format**: `type: short description`

Common types: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`, `ci`, `perf`

## Reporting Issues

- Use [GitHub Issues](https://github.com/ZakPro/codex-proxy/issues) for bugs and feature requests
- Include your Python version, OS, and relevant config (redact API keys)
- For bugs, provide steps to reproduce and any error output

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
