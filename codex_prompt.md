# codex-proxy — Full Upgrade Prompt

Execute all tasks below **in order, phase by phase**. Do NOT skip any task. After each phase, confirm completion before moving to the next. All file paths are relative to `F:\Projects\codex-proxy`.

---

## Phase 1: Foundation (do first, commit after)

### Task 1.1 — Git Init + .gitignore

```bash
cd F:\Projects\codex-proxy
git init
```

Create `.gitignore`:
```gitignore
__pycache__/
*.pyc
*.pyo
*.egg-info/
dist/
build/
.venv/
.env
*.log
.mypy_cache/
.pytest_cache/
.ruff_cache/
```

```bash
git add -A
git commit -m "chore: initial commit — codex-proxy v1.0.0"
```

---

## Phase 2: Bug Fixes (commit each separately)

### Task 2.1 — Usage Tracking in Streaming

**Problem**: Streaming responses always report `usage: {input_tokens: 0, output_tokens: 0, total_tokens: 0}`. Many backends send usage data in the final SSE chunk when `stream_options` is set.

**Changes needed:**

**File: `src/codex_proxy/translator.py`**

In `build_cc_request()` (~line 96), after setting `cc["stream"]`, add:
```python
if cc.get("stream"):
    cc["stream_options"] = {"include_usage": True}
```

In `stream_cc_to_response()`, add a `usage_data` variable initialized to `{"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}`. Inside the `async for line` loop, after processing choices, check for usage in the chunk:
```python
chunk_usage = chunk.get("usage")
if chunk_usage:
    usage_data = {
        "input_tokens": chunk_usage.get("prompt_tokens", 0),
        "output_tokens": chunk_usage.get("completion_tokens", 0),
        "total_tokens": chunk_usage.get("total_tokens", 0),
    }
```
Then use `usage_data` in the final `completed` dict instead of hardcoded zeros.

**File: `src/codex_proxy/server.py`**

Same fix in the WebSocket handler — add `usage_data` tracking, capture usage from chunks, use it in the `completed` dict at line ~275.

```bash
git add -A && git commit -m "fix: capture usage tokens from streaming responses"
```

### Task 2.2 — WebSocket Error Propagation

**Problem**: In `server.py` WebSocket handler (~line 221-223), when upstream errors during streaming, the code logs the error but continues to send `response.completed` with partial/empty text as if the request succeeded.

**Fix**: After the `except Exception as e` block at line 222, send an error event to the client and `continue` to skip the completion events:

```python
except Exception as e:
    logger.error("WS upstream error: %s", e)
    error_resp = {
        "id": rid, "object": "response", "created_at": now,
        "model": model, "status": "failed",
        "output": [], "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        "error": {"message": f"Upstream error: {e}", "code": "upstream_error"},
    }
    await ws.send_text(json.dumps({
        "type": "response.failed", "response": error_resp}))
    continue
```

Make sure the `continue` skips all the "Finish text" / "Build final output" / "response.completed" code that follows.

```bash
git add -A && git commit -m "fix: propagate upstream errors to WebSocket clients instead of fake completion"
```

### Task 2.3 — Graceful Shutdown

**File: `src/codex_proxy/server.py`**

Add a shutdown event handler after the `configure()` function:
```python
@app.on_event("shutdown")
async def shutdown():
    global _client
    if _client:
        await _client.aclose()
        _client = None
    logger.info("codex-proxy shut down")
```

```bash
git add -A && git commit -m "fix: graceful shutdown — close httpx client on exit"
```

### Task 2.4 — Rename `_rid()` to `generate_response_id()`

**File: `src/codex_proxy/translator.py`**
- Rename `def _rid()` to `def generate_response_id()`

**File: `src/codex_proxy/server.py`**
- Update the import: `_rid` → `generate_response_id`
- Update the single call site in the WebSocket handler (~line 152): `rid = generate_response_id()`

```bash
git add -A && git commit -m "refactor: rename _rid() to generate_response_id() for public API clarity"
```

---

## Phase 3: Refactoring (commit each separately)

### Task 3.1 — Eliminate Streaming Duplication

This is the biggest refactor. The SSE parsing logic is duplicated between `translator.py:stream_cc_to_response()` and `server.py` WebSocket handler.

**Create a shared core parser in `translator.py`:**

```python
async def parse_cc_stream(line_iter):
    """Core SSE parser — yields (event_type, data) tuples.
    
    Event types: "text", "reasoning", "tool_call", "usage"
    """
    async for line in line_iter:
        if not line.startswith("data: "):
            continue
        payload = line[6:].strip()
        if payload == "[DONE]":
            break
        try:
            chunk = json.loads(payload)
        except json.JSONDecodeError:
            continue
        for choice in chunk.get("choices", []):
            delta = choice.get("delta", {})
            rc = delta.get("reasoning_content")
            if rc:
                yield ("reasoning", rc)
            txt = delta.get("content")
            if txt:
                yield ("text", txt)
            for tc in delta.get("tool_calls", []):
                yield ("tool_call", tc)
        chunk_usage = chunk.get("usage")
        if chunk_usage:
            yield ("usage", chunk_usage)


def build_final_output(mid: str, full_text: str, reasoning_text: str, tool_calls: list[dict]) -> list[dict]:
    """Build the Responses API output list from accumulated stream data."""
    final_out = []
    if reasoning_text:
        final_out.append({
            "type": "reasoning", "id": f"rs_{uuid.uuid4().hex[:24]}",
            "summary": [{"type": "summary_text", "text": reasoning_text}],
        })
    final_out.append({
        "type": "message", "id": mid, "status": "completed",
        "role": "assistant",
        "content": [{"type": "output_text", "text": full_text, "annotations": []}]
    })
    for tc in tool_calls:
        fc_id = tc["id"] or f"fc_{uuid.uuid4().hex[:24]}"
        final_out.append({
            "type": "function_call", "id": fc_id, "call_id": fc_id,
            "name": tc["function"]["name"],
            "arguments": tc["function"]["arguments"],
            "status": "completed",
        })
    return final_out


def accumulate_tool_call(tool_calls: list[dict], tc: dict) -> None:
    """Accumulate a streaming tool_call delta into the tool_calls list."""
    idx = tc.get("index", 0)
    while len(tool_calls) <= idx:
        tool_calls.append({"id": "", "function": {"name": "", "arguments": ""}})
    if tc.get("id"):
        tool_calls[idx]["id"] = tc["id"]
    fn = tc.get("function", {})
    if fn.get("name"):
        tool_calls[idx]["function"]["name"] = fn["name"]
    if fn.get("arguments"):
        tool_calls[idx]["function"]["arguments"] += fn["arguments"]
```

Then **rewrite `stream_cc_to_response()`** to use `parse_cc_stream()`, `accumulate_tool_call()`, and `build_final_output()`.

Then **rewrite the WebSocket handler's inner loop** in `server.py` to use the same `parse_cc_stream()`, `accumulate_tool_call()`, and `build_final_output()`. The WS handler should iterate over `parse_cc_stream(resp.aiter_lines())` and for each event:
- `"text"` → accumulate + send `response.output_text.delta` via WS
- `"reasoning"` → accumulate
- `"tool_call"` → `accumulate_tool_call()`
- `"usage"` → capture usage

Then use `build_final_output()` to construct `final_out`, and emit the WS completion events.

**Export from translator.py**: `parse_cc_stream`, `build_final_output`, `accumulate_tool_call`

**Update server.py imports** accordingly.

Verify: the HTTP streaming path and WebSocket path should produce **identical output** for the same backend response.

```bash
git add -A && git commit -m "refactor: extract shared streaming core — eliminate 80+ lines of duplication"
```

### Task 3.2 — Global State → AppState

**File: `src/codex_proxy/server.py`**

Replace the 5 module-level globals with a dataclass:

```python
from dataclasses import dataclass, field

@dataclass
class AppState:
    config: ProxyConfig
    store: ResponseStore = field(default_factory=ResponseStore)
    client: httpx.AsyncClient | None = None
    start_time: float = 0.0
    request_count: int = 0
```

- Store it on `app.state.proxy` in `configure()`
- In each endpoint, access via `request.app.state.proxy` (HTTP) or `ws.app.state.proxy` (WS)
- Remove all `global` statements
- Keep backward compatibility: `configure()` still works the same way from `run()`

```bash
git add -A && git commit -m "refactor: move global state to AppState dataclass on app.state"
```

### Task 3.3 — Activate `log_dir`

**File: `src/codex_proxy/server.py`**

In `run()`, after `logging.basicConfig()`, add file handler if log_level is debug:
```python
if config.server.log_level == "debug":
    config.server.log_dir.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(config.server.log_dir / "proxy.log", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s [%(name)s] %(levelname)s %(message)s"))
    logging.getLogger("codex-proxy").addHandler(fh)
```

```bash
git add -A && git commit -m "feat: activate log_dir — write debug logs to ~/.codex-proxy/logs/proxy.log"
```

### Task 3.4 — Configurable Store TTL & Max Entries

**File: `src/codex_proxy/config.py`**

Add a new dataclass:
```python
@dataclass
class StoreConfig:
    ttl_seconds: int = 600
    max_entries: int = 100
```

Add it to `ProxyConfig`:
```python
@dataclass
class ProxyConfig:
    server: ServerConfig = field(default_factory=ServerConfig)
    provider: ProviderConfig = field(default_factory=ProviderConfig)
    store: StoreConfig = field(default_factory=StoreConfig)
```

Load it from TOML `[store]` section in `load_config()`. Add `[store]` section to `write_example_config()`.

**File: `src/codex_proxy/store.py`**

Change `ResponseStore.__init__` to accept `ttl` and `max_entries`:
```python
def __init__(self, ttl_seconds: int = 600, max_entries: int = 100):
    self._store = OrderedDict()
    self.ttl_seconds = ttl_seconds
    self.max_entries = max_entries
```

Remove the class-level `MAX_ENTRIES` and `TTL_SECONDS` constants.

**File: `src/codex_proxy/server.py`**

In `configure()`, create the store with config values:
```python
_store = ResponseStore(
    ttl_seconds=config.store.ttl_seconds,
    max_entries=config.store.max_entries,
)
```

```bash
git add -A && git commit -m "feat: configurable store TTL and max_entries via [store] config section"
```

### Task 3.5 — GET /responses/{id}

**File: `src/codex_proxy/server.py`**

Add endpoint:
```python
@app.get("/responses/{response_id}")
async def get_response(response_id: str):
    resp = _store.get(response_id)  # or state.store.get() if AppState is done
    if not resp:
        return JSONResponse(
            {"error": {"message": "Response not found", "code": "not_found"}},
            status_code=404,
        )
    # Remove internal fields
    clean = {k: v for k, v in resp.items() if not k.startswith("_")}
    return JSONResponse(clean)
```

```bash
git add -A && git commit -m "feat: GET /responses/{id} — retrieve stored responses by ID"
```

### Task 3.6 — Retry Logic

**File: `src/codex_proxy/server.py`**

Add a helper function:
```python
import asyncio

MAX_RETRIES = 1
RETRY_DELAY = 0.5

async def _post_with_retry(url: str, json: dict, headers: dict) -> httpx.Response:
    """POST with one retry on 5xx or transport errors."""
    for attempt in range(MAX_RETRIES + 1):
        try:
            r = await _client.post(url, json=json, headers=headers)
            if r.status_code < 500 or attempt == MAX_RETRIES:
                return r
            logger.warning("Upstream 5xx (attempt %d), retrying...", attempt + 1)
        except httpx.TransportError as e:
            if attempt == MAX_RETRIES:
                raise
            logger.warning("Transport error (attempt %d): %s, retrying...", attempt + 1, e)
        await asyncio.sleep(RETRY_DELAY)
```

Use `_post_with_retry()` in the non-streaming HTTP path instead of direct `_client.post()`.

For streaming paths, do NOT retry (streaming is not idempotent for the client).

```bash
git add -A && git commit -m "feat: retry once on 5xx/transport errors for non-streaming requests"
```

---

## Phase 4: Tests + README + Docker (commit each separately)

### Task 4.1 — Tests

Create `tests/` directory with:

**`tests/conftest.py`**:
```python
import pytest
```

**`tests/test_translator.py`** — test these functions:
- `input_to_messages()` — test with: string input, list of messages, function_call items, function_call_output items, mixed content types, instructions parameter
- `convert_tools()` — test with: None, empty list, function tools, tools with inline name/description
- `build_cc_request()` — test full request building with model, messages, tools, temperature, max_output_tokens
- `cc_to_response()` — test with: text response, reasoning + text, tool calls, empty response
- `unwrap_envelope()` — test with: direct body, `response.create` envelope

**`tests/test_store.py`** — test:
- `put()` / `get()` — basic store/retrieve
- TTL expiry — mock `time.time()` to simulate expiry
- MAX_ENTRIES eviction — store 101 items, verify first is evicted
- `resolve_input()` — test with `previous_response_id`, test without, test with expired previous
- `size()`

**`tests/test_config.py`** — test:
- `load_config()` with no config file (defaults)
- `load_config()` with env vars
- `ProviderConfig.effective_api_key()` — direct key, env var key, fallback
- `write_example_config()` — verify file is created and parseable

Run: `pytest tests/ -v` — all tests must pass.

```bash
git add -A && git commit -m "test: add pytest suite for translator, store, and config"
```

### Task 4.2 — README.md

Create `README.md` in the project root. Structure:

```markdown
# codex-proxy

> Responses API → Chat Completions bridge for OpenAI Codex CLI

Use Codex CLI with **any** Chat Completions-compatible provider:
Z.AI (GLM), Groq, Together AI, OpenRouter, Ollama, Fireworks, and more.

## How It Works

[ASCII diagram: Codex CLI → codex-proxy (localhost:4242) → Any Provider]

## Quick Start

### Install
pip install git+https://github.com/ZakPro/codex-proxy.git

### Configure
codex-proxy --init
# Edit ~/.codex-proxy/config.toml

### Run
codex-proxy

### Connect Codex CLI
# ~/.codex/auth.json
{"api_key": "your-key", "api_base": "http://localhost:4242"}

## Configuration

[Full config.toml reference with all providers]

## Provider Examples

[Z.AI, Groq, Together, OpenRouter, Ollama, Fireworks — each with config snippet]

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| /responses | POST | Responses API (HTTP) |
| /responses | WS | Responses API (WebSocket) |
| /responses/{id} | GET | Retrieve stored response |
| /models | GET | List available models |
| /health | GET | Health check |
| /status | GET | Detailed status |

## Auto-Start (Windows)

[VBS script setup instructions]

## Environment Variables

| Variable | Description |
|---|---|
| CODEX_PROXY_API_KEY | API key |
| CODEX_PROXY_BASE_URL | Provider base URL |
| CODEX_PROXY_MODEL | Default model |
| OPENAI_API_KEY | Fallback API key |

## License

MIT
```

```bash
git add -A && git commit -m "docs: add comprehensive README"
```

### Task 4.3 — Dockerfile

Create `Dockerfile` in project root:
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml .
COPY src/ src/
RUN pip install --no-cache-dir .
EXPOSE 4242
ENV CODEX_PROXY_API_KEY=""
ENV CODEX_PROXY_BASE_URL=""
CMD ["codex-proxy"]
```

Create `.dockerignore`:
```
__pycache__
*.pyc
.git
.venv
.env
tests/
```

```bash
git add -A && git commit -m "feat: add Dockerfile for containerized deployment"
```

---

## Final Verification

After all phases are complete:

1. `pytest tests/ -v` — all tests pass
2. `codex-proxy --print-config` — works correctly
3. `git log --oneline` — verify clean commit history
4. Review the final state of all files — no leftover dead code, no broken imports

Report the final `git log --oneline` output and any issues encountered.
