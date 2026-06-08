# mlx-mcp-server

A [Model Context Protocol (MCP)](https://modelcontextprotocol.io) server that gives Claude Code and Claude Desktop a set of tools to talk to a locally-running LLM. Optimised for [oMLX](https://omlx.ai) and [MLX LM](https://github.com/ml-explore/mlx-lm) on Apple Silicon, with support for any OpenAI-compatible backend (Ollama, LM Studio, etc.).

**The idea:** Claude stays Claude. Your local model becomes a tool Claude can call — fast, private, free, and clearly labelled `🏠 LOCAL` in every response.

---

## How it works

```
You (in Claude Code or Claude Desktop)
        │
        ▼
  Claude (Sonnet / your tier)          ← still the primary AI
        │
        │  calls MCP tools when useful
        ▼
  mlx-mcp-server  (subprocess)         ← this repo
        │
        │  HTTP  POST /v1/chat/completions
        ▼
  Your local LLM backend               ← oMLX · MLX LM · Ollama · LM Studio
        │
        ▼
  Response with 🏠 LOCAL badge         ← so you always know which model answered
```

Claude Code spawns `mlx-mcp-server` as a background subprocess at startup. The server sits idle until you — or Claude — explicitly invoke one of its tools. Nothing is routed automatically; you're always talking to real Claude unless a tool is called.

---

## Quick install

> **macOS with Homebrew Python** — use `uv` (pip is blocked by PEP 668):
> ```bash
> uv tool install mlx-mcp-server
> ```
>
> **Other environments:**
> ```bash
> pip install mlx-mcp-server
> ```

### oMLX (recommended on Apple Silicon)

```bash
# Add to Claude Code
mlx-mcp-server install --claude-code \
  --base-url http://localhost:8000 \
  --api-key YOUR_OMLX_KEY \
  --model "Qwen3.6-35B-A3B-4bit"

# Add to Claude Desktop
mlx-mcp-server install \
  --base-url http://localhost:8000 \
  --api-key YOUR_OMLX_KEY \
  --model "Qwen3.6-35B-A3B-4bit"
```

### MLX LM

```bash
# Start the server first
mlx_lm.server --model mlx-community/Mistral-7B-Instruct-v0.3-4bit

# Then install (no API key needed, model auto-detected)
mlx-mcp-server install --claude-code --base-url http://localhost:8080
```

### Ollama

```bash
ollama serve && ollama pull mistral

mlx-mcp-server install --claude-code \
  --base-url http://localhost:11434 \
  --model mistral
```

Restart Claude Code / Claude Desktop after installing.

---

## Tools

These are the MCP tools Claude can call. You can invoke them directly by name in conversation, or ask Claude to use the local model for a specific task.

### `chat`

Send a message to your local LLM and get a response.

```
# In Claude Code — just say it:
"Use the local model to write a SQL migration for adding a users table"
"Ask the local model to summarise this error log"
"Use local: write boilerplate for a new Go HTTP handler"
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `message` | string | required | The prompt to send |
| `system_prompt` | string | `""` | Optional system prompt (overrides default) |
| `temperature` | float | `0.7` | Sampling temperature |
| `max_tokens` | int | `512` | Max response tokens |
| `top_p` | float | `1.0` | Nucleus sampling |
| `top_k` | int | `0` | Top-k sampling (0 = disabled) |

**Response format:**
```
🏠 LOCAL · Qwen3.6-35B-A3B-4bit

[model response here]

---
Tokens: 12 prompt + 48 completion = 60 total | 1.24s
```

---

### `quick_test`

Run a predefined diagnostic prompt to benchmark your model and verify it's working.

```
quick_test math        # 347 × 28 — tests reasoning + speed
quick_test hello       # intro prompt — tests personality / identity
quick_test creative    # two-sentence robot story — tests creativity
quick_test code_review # Python snippet review — tests code understanding
```

**Response format:**
```
Test: math
Prompt: What is 347 × 28? Show your working.

Response:
347 × 28 = 9,716  [working shown]

---
🏠 LOCAL · Qwen3.6-35B-A3B-4bit · 54.7 tok/s · 312 tokens · 5.71s
```

---

### `health_check`

Verify your LLM backend is reachable and report what's loaded.

```
health_check
```

**Response (oMLX):**
```json
{
  "status": "ok",
  "url": "http://localhost:8000",
  "models_loaded": "1/2"
}
```

**Response (unreachable):**
```json
{
  "status": "unreachable",
  "url": "http://localhost:8000",
  "hint": "Make sure your LLM backend is running at http://localhost:8000."
}
```

---

### `list_models`

List the models available on your backend.

```
list models
```

**Response:**
```
- Qwen3.5-27B-4bit
- Qwen3.6-35B-A3B-4bit
```

---

## Configuration

Set via environment variables, or use the `install` command to write them automatically.

| Variable | Default | Description |
|----------|---------|-------------|
| `MLX_BASE_URL` | `http://localhost:8080` | Backend URL |
| `MLX_DEFAULT_MODEL` | `""` | Model name. If empty, auto-detected from `/v1/models` on first call |
| `MLX_API_KEY` | `""` | API key for secured backends (e.g. oMLX) |
| `MLX_TIMEOUT` | `30` | Request timeout in seconds |

### Auto-detection

When `MLX_DEFAULT_MODEL` is not set, the server queries `/v1/models` on the first `chat` call and uses whatever model the backend reports. The result is cached for the session. This works well for single-model backends (MLX LM, Ollama). For oMLX with multiple configured models, set `MLX_DEFAULT_MODEL` explicitly since oMLX lists all configured models, not just the loaded one.

---

## Install command reference

```bash
mlx-mcp-server install [options]
```

| Flag | Description |
|------|-------------|
| `--claude-code` | Target Claude Code (`~/.claude/settings.json`) instead of Claude Desktop |
| `--base-url URL` | Backend URL (default: `http://localhost:8080`) |
| `--model NAME` | Model name — optional, auto-detected if omitted |
| `--api-key KEY` | API key for secured backends |
| `--dry-run` | Print the config that would be written without touching any files |

**Preview before writing:**
```bash
mlx-mcp-server install --claude-code \
  --base-url http://localhost:8000 \
  --api-key mykey \
  --model "Qwen3.6-35B-A3B-4bit" \
  --dry-run
```

**Update model without changing other settings** (just re-run with new `--model`):
```bash
mlx-mcp-server install --claude-code \
  --base-url http://localhost:8000 \
  --api-key mykey \
  --model "Qwen3.5-27B-4bit"
```

---

## Manual config

If you prefer to edit the config file directly:

**Claude Desktop** — `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS)

**Claude Code** — `~/.claude/settings.json`

```json
{
  "mcpServers": {
    "mlx": {
      "command": "mlx-mcp-server",
      "env": {
        "MLX_BASE_URL": "http://localhost:8000",
        "MLX_DEFAULT_MODEL": "Qwen3.6-35B-A3B-4bit",
        "MLX_API_KEY": "your-key-here"
      }
    }
  }
}
```

---

## Supported backends

| Backend | Platform | Default port | Notes |
|---------|----------|-------------|-------|
| [oMLX](https://omlx.ai) | macOS (Apple Silicon) | 8000 | Requires API key + explicit model name |
| [MLX LM](https://github.com/ml-explore/mlx-lm) | macOS (Apple Silicon) | 8080 | No auth needed, model auto-detected |
| [Ollama](https://ollama.ai) | macOS / Linux / Windows | 11434 | Set `MLX_DEFAULT_MODEL` to model name |
| [LM Studio](https://lmstudio.ai) | macOS / Windows | 1234 | Enable "Local Server" in LM Studio |

---

## oMLX-specific notes

[oMLX](https://omlx.ai) is a native macOS GUI for running MLX models on Apple Silicon. A few quirks to know:

- **Port:** listens on `127.0.0.1:8000` (not 8080)
- **API key required:** set one in oMLX settings and pass it via `--api-key`
- **Model field required:** oMLX returns 422 if `model` is omitted from requests — always set `MLX_DEFAULT_MODEL`
- **`/health` endpoint:** unauthenticated, returns engine pool info — `health_check` uses this first
- **MoE models:** `Qwen3.6-35B-A3B-4bit` activates only ~3B params per token — 5–6× faster than dense 27B models at the same quality level

---

## Requirements

- Python 3.11+
- A running OpenAI-compatible LLM backend

---

## Development

```bash
git clone https://github.com/deresolution20/mlx-mcp-server
cd mlx-mcp-server

# Install with dev dependencies
uv sync --dev

# Run tests
uv run pytest tests/ -v

# Install locally for testing
uv tool uninstall mlx-mcp-server 2>/dev/null
uv tool install . --no-cache
```

---

## License

MIT
