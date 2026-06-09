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
  --model "Qwen3-Coder-30B-A3B-Instruct-MLX-4bit"

# Add to Claude Desktop
mlx-mcp-server install \
  --base-url http://localhost:8000 \
  --api-key YOUR_OMLX_KEY \
  --model "Qwen3-Coder-30B-A3B-Instruct-MLX-4bit"
```

Also install the slash commands and helper scripts in one shot:

```bash
mlx-mcp-server install --claude-code \
  --base-url http://localhost:8000 \
  --api-key YOUR_OMLX_KEY \
  --model "Qwen3-Coder-30B-A3B-Instruct-MLX-4bit" \
  --full
```

### MLX LM

```bash
# Start the server first
mlx_lm.server --model mlx-community/Qwen2.5-Coder-14B-Instruct-4bit

# Then install (no API key needed, model auto-detected)
mlx-mcp-server install --claude-code --base-url http://localhost:8080
```

### Ollama

```bash
ollama serve && ollama pull qwen2.5-coder:14b

mlx-mcp-server install --claude-code \
  --base-url http://localhost:11434 \
  --model qwen2.5-coder:14b
```

Restart Claude Code / Claude Desktop after installing.

---

## Tested model lineup (Apple Silicon)

These models were live-tested on an **M5 MacBook Pro (32 GB)** and benchmarked with `quick_test code_review`. All speeds are measured — not estimated from spec sheets.

| Tier | Model | RAM | tok/s | Best for |
|------|-------|-----|-------|----------|
| ⚡ Turbo | `DeepSeek-Coder-V2-Lite-Instruct-4bit-mlx` | ~8 GB | ~135 | Quick lookups, boilerplate, instant subagent calls |
| ⚡ Fast | `Qwen2.5-Coder-7B-Instruct-4bit` | ~5 GB | ~80 | Speed fallback, lightweight code tasks |
| ⚖️ Default | `Qwen2.5-Coder-14B-Instruct-4bit` | ~9 GB | ~28 | Reliable everyday coding, code review |
| 🧠 Quality | `Qwen3-Coder-30B-A3B-Instruct-MLX-4bit` | ~18 GB | ~51 | Best coding quality — MoE (3B active params), no thinking mode |

The quality tier runs at **~51 tok/s despite 30B parameters** because it's a Mixture of Experts model — only ~3B parameters are active per token. It fits in 18 GB and doesn't activate a thinking chain, making it ideal for subagent use.

---

## Model research & findings

During development, several models were evaluated. Here's what was tested and why each was accepted or rejected.

### Accepted

| Model | Verdict | Notes |
|-------|---------|-------|
| `DeepSeek-Coder-V2-Lite-Instruct-4bit-mlx` | ✅ Kept | ~135 tok/s on M5/32GB. Fastest option — unmatched for quick lookups and boilerplate. |
| `Qwen2.5-Coder-7B-Instruct-4bit` | ✅ Kept | ~80 tok/s. Speed fallback — dominates when 14B is too slow and turbo is overkill. |
| `Qwen2.5-Coder-14B-Instruct-4bit` | ✅ Kept | ~28 tok/s. Reliable everyday default. No non-thinking upgrade path exists at this size as of June 2026 (Qwen3-Coder goes no smaller than 30B-A3B). |
| `Qwen3-Coder-30B-A3B-Instruct-MLX-4bit` | ✅ Kept | ~51 tok/s. Best quality. MoE architecture means 30B params but only ~3B active per token. Clean output — no thinking chain. |

### Rejected

| Model | Verdict | Reason |
|-------|---------|--------|
| `Qwen2.5-Coder-32B-Instruct-4bit` | ❌ Dropped | Strictly dominated by Qwen3-Coder-30B-A3B: slower (~19 tok/s vs ~51), older generation, same RAM footprint. |
| `Qwen3-Coder-30B-A3B-Instruct-MLX-6bit` | ❌ Dropped | 24.26 GB — too tight for 32 GB system even with Big Model Mode. Can't load reliably. |
| `Qwen3.6-35B-A3B-Instruct-4bit` | ❌ Dropped | Thinking model — burns 2,100+ tokens on internal reasoning before every answer. Measured 39 seconds for a 3-sentence code review. Unusable as a subagent. |
| `Gemma 4 31B (5-bit)` | ❌ Dropped | Two blockers: (1) oMLX rejects `enable_thinking` field → 400 Bad Request (fixed in client); (2) `tokenizer.chat_template is not set` — fundamental oMLX incompatibility, not fixable client-side. |
| `Gemma 3 27B QAT 4bit` | ❌ Dropped | Measured ~7.5 tok/s on M5/32GB (not the ~35 tok/s seen in some benchmarks). Strictly dominated by Qwen3-Coder-30B-A3B on every axis: 7× slower, same RAM, same quality tier. |

### Key findings

- **MoE models beat dense models at the quality tier.** `Qwen3-Coder-30B-A3B` at 51 tok/s is faster than `Qwen2.5-Coder-32B` at 19 tok/s, with better quality. Active params (not total params) determine speed.
- **Avoid thinking models for subagent use.** `Qwen3.6-35B-A3B` and other `/think`-default models spend thousands of tokens reasoning before outputting a single word. Claude already handles the reasoning — your local model just needs to answer.
- **Benchmark on your hardware.** Published tok/s numbers for Gemma 3 27B QAT diverged significantly from measured M5/32GB performance. Always verify with `quick_test` before committing to a model.
- **`enable_thinking` payload safety.** The client only sends `enable_thinking: true` when explicitly requested. Sending `enable_thinking: false` unconditionally causes 400 errors on models that don't recognise the field (e.g., Gemma 4). See [#1559](https://github.com/ml-explore/mlx-lm/issues/1559) for the DFlash speculative decoding issue that routes Gemma 4 output to `reasoning_content`.

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
🏠 LOCAL · Qwen3-Coder-30B-A3B-Instruct-MLX-4bit

[model response here]

---
Tokens: 12 prompt + 48 completion = 60 total | 1.24s
```

---

### `quick_test`

Run a predefined diagnostic prompt to benchmark your model and verify it's working.

```
quick_test hello       # intro prompt — tests basic response
quick_test code_review # Python snippet review — tests code understanding
quick_test math        # 347 × 28 — tests reasoning + speed
```

**Response format:**
```
Test: code_review
Prompt: Review this Python function: ...

Response:
[model code review]

---
🏠 LOCAL · Qwen3-Coder-30B-A3B-Instruct-MLX-4bit · 51.3 tok/s · 180 tokens · 3.51s
```

---

### `list_models`

List the models available on your backend with descriptions.

```
list models
```

**Response (oMLX with all four tiers loaded):**
```
Models available at http://localhost:8000:

• DeepSeek-Coder-V2-Lite-Instruct-4bit-mlx
  ⚡ Turbo — ~135 tok/s, instant subagent calls, quick lookups & boilerplate

• Qwen2.5-Coder-7B-Instruct-4bit
  ⚡ Fast — ~80 tok/s, speed fallback, solid code quality

• Qwen2.5-Coder-14B-Instruct-4bit
  ⚖️  Everyday — ~28 tok/s, reliable default for most coding tasks

• Qwen3-Coder-30B-A3B-Instruct-MLX-4bit
  🧠 Quality — ~51 tok/s, best coding quality, MoE (3B active), no thinking mode
```

---

### `set_model`

Switch the active model by name or fragment. The work-hours guard prevents accidentally loading big models during Grafana hours.

```
set_model(model_name="14b")           # fuzzy match → Qwen2.5-Coder-14B-Instruct-4bit
set_model(model_name="30b")           # fuzzy match → Qwen3-Coder-30B-A3B-Instruct-MLX-4bit
set_model(model_name="", force=True)  # clear override, auto-detect from backend
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `model_name` | string | required | Model name or fragment (fuzzy matched) |
| `force` | bool | `false` | Bypass work-hours guard for big models |

---

### `health_check`

Verify your LLM backend is reachable and report what's loaded.

**Response (oMLX):**
```json
{
  "status": "ok",
  "url": "http://localhost:8000",
  "models_loaded": "1/4"
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

### `get_config`

Show current URL, active model, timeout, and work-hours guard state.

```json
{
  "base_url": "http://localhost:8000",
  "active_model": "Qwen3-Coder-30B-A3B-Instruct-MLX-4bit",
  "model_source": "file",
  "timeout_seconds": 30,
  "work_hours_guard": false
}
```

---

### `set_work_hours_guard`

Toggle a guard that blocks big model loads during weekday business hours (8am–5pm MT). Useful if you share system RAM with work VMs and don't want a 18 GB model load mid-meeting.

```
set_work_hours_guard(enabled=True)   # on — blocks big models 8am–5pm MT weekdays
set_work_hours_guard(enabled=False)  # off (default)
```

---

## Slash commands

Install with `--full` or `--with-commands` to get these in `~/.claude/commands/`:

| Command | What it does |
|---------|--------------|
| `/switch-model` | List available models and switch interactively |
| `/big-model` | Free RAM by closing apps, then load the 30B quality model |
| `/big-model-done` | Switch back to 14B and reopen closed apps |
| `/mlx-help` | Display a live reference card (pulls config via `get_config`) |

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

When `MLX_DEFAULT_MODEL` is not set, the server queries `/v1/models` on the first `chat` call and uses whatever model the backend reports. The result is cached for the session. This works well for single-model backends (MLX LM, Ollama). For oMLX with multiple configured models, set `MLX_DEFAULT_MODEL` explicitly — oMLX lists all configured models, not just the loaded one.

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
| `--with-commands` | Copy slash commands to `~/.claude/commands/` |
| `--with-scripts` | Copy helper shell scripts to `~/bin/` |
| `--full` | Shorthand for `--with-commands --with-scripts` |
| `--dry-run` | Print the config that would be written without touching any files |

**Preview before writing:**
```bash
mlx-mcp-server install --claude-code \
  --base-url http://localhost:8000 \
  --api-key mykey \
  --model "Qwen3-Coder-30B-A3B-Instruct-MLX-4bit" \
  --dry-run
```

**Full install (MCP config + slash commands + scripts):**
```bash
mlx-mcp-server install --claude-code \
  --base-url http://localhost:8000 \
  --api-key mykey \
  --model "Qwen3-Coder-30B-A3B-Instruct-MLX-4bit" \
  --full
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
        "MLX_DEFAULT_MODEL": "Qwen3-Coder-30B-A3B-Instruct-MLX-4bit",
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
- **MoE models:** `Qwen3-Coder-30B-A3B-Instruct-MLX-4bit` activates only ~3B params per token — faster than dense 14B models at higher quality
- **Thinking models:** Disable the "Enable Thinking" toggle in oMLX Advanced settings for any Qwen3 general or Qwen3.6 model before using it as a subagent. Thinking mode burns thousands of tokens before each answer.
- **`enable_thinking` payload:** The client only sends this field when explicitly `True`. Sending `enable_thinking: false` unconditionally causes 400 errors on models that don't recognise it.
- **DFlash / speculative decoding:** Disable DFlash for Gemma models in oMLX — it routes output to `reasoning_content` instead of `content`, causing empty responses.

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
