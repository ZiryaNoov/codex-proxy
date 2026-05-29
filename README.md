# codex-proxy

> Responses API to Chat Completions bridge for OpenAI Codex CLI

Use Codex CLI with **any** Chat Completions-compatible provider:
Z.AI (GLM), Groq, Together AI, OpenRouter, Ollama, Fireworks, and more.

## How It Works

```
┌────────────┐     ┌──────────────┐     ┌──────────────┐
│ Codex CLI  │────>│ codex-proxy  │────>│ Any Provider │
│            │<────│ :4242        │<────│ (CC API)     │
└────────────┘     └──────────────┘     └──────────────┘
                   Responses API        Chat Completions
                   protocol             protocol
```

Codex CLI only speaks the Responses API. Most providers only speak Chat Completions.
codex-proxy translates between the two in real time.

## Quick Start

### Install

```bash
pip install git+https://github.com/ZiryaNoov/codex-proxy.git
```

### Configure

```bash
codex-proxy --init
# Edit ~/.codex-proxy/config.toml with your provider details
```

### Run

```bash
codex-proxy
```

### Connect Codex CLI

Edit `~/.codex/config.toml`:

```toml
model = "glm-5.1"
openai_base_url = "http://127.0.0.1:4242"
```

Edit `~/.codex/auth.json`:

```json
{
  "auth_mode": "apikey",
  "OPENAI_API_KEY": "your-provider-api-key"
}
```

## Configuration

Config file: `~/.codex-proxy/config.toml`

```toml
[server]
host = "127.0.0.1"
port = 4242
log_level = "warning"    # debug, info, warning, error

[store]
ttl_seconds = 600         # response cache TTL
max_entries = 100         # max cached responses

[provider]
name = "zai"
display_name = "Z.AI"
base_url = "https://api.z.ai/api/paas/v4"
api_key = ""              # or use api_key_env
api_key_env = "OPENAI_API_KEY"
models = ["glm-5.1", "glm-5", "glm-4.7"]
default_model = "glm-5.1"
```

## Provider Examples

### Z.AI (GLM Models)

```toml
[provider]
name = "zai"
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

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/responses` | POST | Responses API (HTTP, streaming + non-streaming) |
| `/responses` | WS | Responses API (WebSocket) |
| `/responses/{id}` | GET | Retrieve stored response by ID |
| `/models` | GET | List available models |
| `/v1/models` | GET | List available models (v1 prefix) |
| `/health` | GET | Health check (`?check_backend=true` pings upstream) |
| `/status` | GET | Detailed server status |
| `/reload` | POST | Reload config from disk |

## Features

- **Protocol translation**: Responses API to Chat Completions, both directions
- **Streaming SSE**: Real-time token streaming with proper event formatting
- **WebSocket support**: Full Realtime API envelope handling
- **Reasoning passthrough**: Forwards reasoning/thinking tokens from supported models
- **Tool calls**: Full function calling support (definitions + results)
- **Multi-turn**: `previous_response_id` support via in-memory response store
- **Multi-provider**: Switch backends with a single config change
- **Usage tracking**: Captures token counts from streaming responses
- **Auto-retry**: One retry on 5xx/transport errors for non-streaming requests
- **Configurable**: TOML config file, env vars, CLI flags

## CLI Options

```
codex-proxy                  # Start proxy server
codex-proxy --port 8080      # Override port
codex-proxy --host 0.0.0.0   # Override bind host
codex-proxy --config PATH    # Use custom config file
codex-proxy --init           # Write example config and exit
codex-proxy --print-config   # Print resolved config and exit
```

## Auto-Start (Windows)

Create a VBS file in your Startup folder (`%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup`):

```vbs
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run """C:\Path\To\python.exe"" -m codex_proxy", 0, False
```

## Environment Variables

| Variable | Description |
|---|---|
| `CODEX_PROXY_API_KEY` | API key for the provider |
| `CODEX_PROXY_BASE_URL` | Provider base URL |
| `CODEX_PROXY_MODEL` | Default model name |
| `OPENAI_API_KEY` | Fallback API key |

## Development

```bash
git clone https://github.com/ZakPro/codex-proxy.git
cd codex-proxy
pip install -e .
pytest tests/ -v
```

## License

MIT
