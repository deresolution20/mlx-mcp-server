# Mlx Mcp Server

![AI Automation](https://img.shields.io/badge/AI%20Automation-Consultant-blueviolet) ![Language](https://img.shields.io/badge/Language-Python-blue) ![License](https://img.shields.io/badge/License-MIT-green) ![Tests](https://img.shields.io/badge/Tests-pytest-success) ![CI](https://img.shields.io/badge/CI-GitHub%20Actions-success)

> MCP server bridging Claude to local MLX LM (and any OpenAI-compatible backend)

_AI automation consulting — I help businesses replace painful manual processes with LLM-powered pipelines and workflow automation._

---

## Overview

This repository is part of my professional portfolio. It is written primarily in **Python** and maintained with professional standards: documented, licensed, and (where applicable) tested and CI'd.

## Features

- Clean, documented, production-minded code.
- MIT licensed for open reuse.
- Designed for reviewability — clear structure, clear README.

## Getting Started

```bash
# Clone
git clone https://github.com/deresolution20/mlx-mcp-server.git
cd mlx-mcp-server
```

## Usage

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
| ⚖️ Everyday | `Qwen2.5-Coder-14B-Instruct-4bit` | ~9 GB | ~28 | Reliable everyday coding, code review |
| 🧠 **Default** | `Qwen3-Coder-30B-A3B-Instruct-MLX-4bit` | ~18 GB | ~51 | Best quality **and the shipped default** — MoE (3B active params), no thinking mode |

The quality tier runs at **~51 tok/s despite 30B parameters** because it's a Mixture of Experts model — only ~3B parameters are active per token. It fits in 18 GB and doesn't activate a thinking chain, making it ideal for subagent use.

**As of v0.2.4 the 30B-A3B is the shipped default.** A 24-case gated eval across six task categories (see [reports](#design--eval-reports) below) found it passes everything at **~0.6 s median latency — as fast as the turbo tier** — so there's no reason to default to a smaller model and escalate. The earlier multi-model "warm pool" scaffolding was dropped: the MoE makes the big model cheap enough to simply be the default.

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
- **On bounded work, speed is the differentiator — not quality.** The gated eval harness (`python -m mlx_mcp_server.eval run`) found every coding model passes nearly all easy/medium cases; they separate on latency. The MoE 30B-A3B wins by being top-quality *and* turbo-fast. (Harder cases that separate models on quality are what the Phase-2 capture loop is for.)
- **You can't sweep all models in one engine pool.** Loading the small models first fills the ~24.5 GB pool, so the big ones then return `507 Insufficient Storage`. Evaluate big models in isolation (one ~17 GB model at a time). This warm-pool/eviction limit is a hard constraint for any future auto-ladder selector.

### Design & eval reports

Research notes and measured results captured during development (open in a browser):

- [`docs/eval-results-report.html`](docs/eval-results-report.html) — full 5-model gated eval: pass-rate, latency, and tokens per task category, with the ladder recommendation.
- [`docs/task-aware-routing-brainstorm.html`](docs/task-aware-routing-brainstorm.html) — routing design v1: cascade vs. pre-route under a memory ceiling.
- [`docs/task-aware-routing-brainstorm-v2.html`](docs/task-aware-routing-brainstorm-v2.html) — v2: the warm-pool reframe and the single-GPU parallelism reality check.
- [`docs/task-aware-routing-brainstorm-v3.html`](docs/task-aware-routing-brainstorm-v3.html) — v3: GLM-5.2 won't fit 24 GB; Self-MoA shows weak-model councils underperform; best-of-N with the gate as verifier.

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

## Offload-first (token thrift)

This server is built to absorb work that would otherwise spend Claude tokens.

**Tier 1 — portable (zero config).** When the server is connected, it advertises
an offload-first instructions block, so any agent using it is told to route
eligible work (summarize, boilerplate, single-file review, extract, explain,
simple refactors) through the `iterate` tool first, tag a `category`, and keep
multi-file reasoning + judgment on Claude.

**The `iterate` tool.** Runs a local-first escalation ladder: the active local
model retries (feeding the gate's failure text back in) up to `max_local_rounds`,
then optionally one attempt on a bigger local model (`big_model`), then escalates
to Claude. Provide a gate so retries can improve:
- Structural: `require_json`, `schema_keys`, `contains`, `regex`, `min_len`.
- Executable: `check_command` — a shell command that reads the candidate at
  `$CANDIDATE_FILE` and exits 0 to pass (e.g. `pytest`, `ruff`).
- No gate → single local attempt, returned for you to verify.

Counts only are logged to `~/.omlx/mlx-call-log.jsonl` (model, category, tokens,
rounds, winning rung) — never prompt/response content.

**Tier 2 — power-up (one command).** Install Claude Code hooks + an `/offload`
skill that reinforce the policy:

```bash
mlx-mcp-server install --claude-code --with-offload   # or --full for everything
```

---

## Slash commands

Install with `--full` or `--with-commands` to get these in `~/.claude/commands/`:

| Command | What it does |
|---------|--------------|
| `/switch-model` | List available models (queried live from oMLX, so new downloads appear automatically) and switch interactively |
| `/mlx-help` | Display a live reference card (pulls config via `get_config`) |

---

## Offload enforcement hook

A `UserPromptSubmit` hook classifies each prompt on the local model and, for offloadable work (summarize, extract, classify, draft, and single-file code), generates the answer locally and injects it as a draft for the assistant to verify — turning the offload policy from advisory into enforced. Logs counts/labels only (never prompt or response text) to `~/.omlx/mlx-call-log.jsonl` and `~/.omlx/hook-decisions.jsonl`.

### Two failure modes

1. **Silent quality gate escalation:** If a local answer fails the quality gate (too short, code doesn't compile), it escalates silently to Claude without injecting a draft.
2. **Loud infrastructure pause:** If oMLX itself is unreachable (transport error, timeout, non-2xx), the hook runs `omlx restart` and injects a directive telling the assistant to surface the error and PAUSE — never a silent fallback to Claude.

### Wiring it up (manual)

You must add this to `~/.claude/settings.json` — the installer does **NOT** edit settings automatically:

```json
{
  "hooks": {
    "UserPromptSubmit": [
      { "hooks": [ { "type": "command", "command": "mlx-offload-hook" } ] }
    ]
  }
}
```

`mlx-offload-hook` is installed on PATH via `uv tool install mlx-mcp-server` (`~/.local/bin`), and it reads oMLX credentials from `~/.claude/settings.json` → `mcpServers.mlx.env`. After adding the hook, restart Claude Code.

### Case-2 live drill

`mlx-case2-drill` fires the hook's infrastructure-failure path (Case 2) for real,
once, on demand — proving the live recovery works end-to-end. Run it only when
oMLX is **idle and healthy**; it briefly stops the server.

It pre-checks health (aborts if already down, so it never masks a real outage),
forces an outage with `omlx stop`, pipes a fixed offloadable prompt into the live
`mlx-offload-hook`, and asserts: the hook exits 0, injects the PAUSE directive,
logs exactly one counts-only `infra_error` decision, and that the hook's own
`omlx restart` brought the server back. If recovery failed, the drill runs
`omlx start` itself as a backstop and reports **FAIL**.

```bash
mlx-case2-drill   # exit 0 = PASS, 1 = FAIL, 2 = aborted (oMLX already down)
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
# Install dev dependencies
pip install -r requirements-dev.txt  # if present
# Run tests
pytest -q
```

## License

MIT — see [LICENSE](LICENSE).

---

<div align="center">

<sub>Built and maintained by **Brice** — Observability Engineer at Grafana Labs / AI Automation Consultant. See more at [github.com/deresolution20](https://github.com/deresolution20).</sub>

</div>
