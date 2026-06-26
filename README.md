# Mlx Mcp Server

[![PyPI version](https://img.shields.io/pypi/v/mlx-mcp-server.svg)](https://pypi.org/project/mlx-mcp-server/)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://pypi.org/project/mlx-mcp-server/)
[![License: MIT](https://img.shields.io/github/license/deresolution20/mlx-mcp-server.svg)](https://github.com/deresolution20/mlx-mcp-server/blob/main/LICENSE)
[![Publish to PyPI](https://github.com/deresolution20/mlx-mcp-server/actions/workflows/publish.yml/badge.svg)](https://github.com/deresolution20/mlx-mcp-server/actions/workflows/publish.yml)
[![AI Automation Consultant](https://img.shields.io/badge/AI%20Automation-Consultant-blueviolet)](https://github.com/deresolution20)

> MCP server bridging Claude to local MLX LM (and any OpenAI-compatible backend)

_AI automation consulting — I help businesses replace painful manual processes with LLM-powered pipelines and workflow automation._

---

## Overview

`mlx-mcp-server` is a [Model Context Protocol](https://modelcontextprotocol.io) server that bridges Claude to a **local** LLM (MLX LM on Apple Silicon, or any OpenAI-compatible `/v1` backend) so Claude can hand off eligible work to a free, private model instead of spending paid tokens.

Rather than a plain pass-through, it enforces an **offload-first** policy: its headline `iterate` tool runs a self-correcting escalation ladder — retry locally against a gate, step up to a bigger local model, and only escalate to Claude when the local rungs are exhausted. The result is lower token cost and more privacy for routine work (summarizing, extracting, classifying, boilerplate, single-file review), while Claude stays focused on multi-file reasoning and judgment calls.

## Features

- **Offload-first, token-thrift** — routes eligible work (summarize, extract, classify, boilerplate, single-file review, first drafts) to a free, private local model before spending paid Claude tokens.
- **Self-correcting `iterate` ladder** — retries locally, then a bigger local model, then escalates to Claude; free rungs are exhausted before any paid work.
- **Gated retries** — structural gates (`require_json` / `schema_keys` / `contains` / `regex` / `min_len`) and an executable gate (run a linter or test against `$CANDIDATE_FILE`) let the local model fix its own output.
- **Runtime model switching** — swap the active model by name or fuzzy fragment with no Claude restart; choice persists across restarts.
- **Work-hours guard** — optionally blocks large (>22 GB RAM) models during work hours to avoid swap thrashing.
- **One-step install** — wires the MCP server and slash commands (`/switch-model`, `/mlx-help`) into Claude Code or Claude Desktop.
- **Backend-agnostic** — works with MLX LM or any OpenAI-compatible `/v1` endpoint; content-free usage metrics, MIT licensed, tested and CI'd.

## Getting Started

Requires Python 3.11+ and a running OpenAI-compatible LLM backend (MLX LM on Apple Silicon is recommended).

```bash
pip install mlx-mcp-server
mlx-mcp-server install --claude-code --with-commands   # wire into Claude Code, then restart Claude
```

See [Usage](#usage) for backend setup, configuration, and the full tool reference.

## Usage

### 1. Start a local LLM backend

The server talks to any OpenAI-compatible `/v1` endpoint. On Apple Silicon, [MLX LM](https://github.com/ml-explore/mlx-lm) is recommended:

```bash
pip install mlx-lm
mlx_lm.server --model mlx-community/Qwen2.5-Coder-14B-Instruct-4bit   # serves on http://localhost:8080
```

Any other OpenAI-compatible backend works too (e.g. Ollama on Linux/Intel — point `MLX_BASE_URL` at `http://localhost:11434`).

### 2. Install and wire it into Claude

```bash
pip install mlx-mcp-server

# One-step setup for Claude Code (also installs the /switch-model + /mlx-help slash commands)
mlx-mcp-server install --claude-code --with-commands

# ...or Claude Desktop
mlx-mcp-server install --with-commands

# Preview the config without writing anything
mlx-mcp-server install --claude-code --dry-run
```

The installer writes an `mlx` entry into your Claude config (`~/.claude/settings.json` for Claude Code, or the Claude Desktop config). **Restart Claude afterward** to load the server. Verify the backend is reachable with the `health_check` tool, or run `mlx-mcp-server help` for the full CLI reference.

### 3. How Claude uses it — offload-first

The whole point is **token thrift**: Claude routes eligible work (summarize, extract, classify, reformat, boilerplate, single-file review, simple refactors, first drafts) to your free, private local model before spending paid tokens. The headline tool is `iterate`, which runs a self-correcting escalation ladder:

> **local model retries** (feeding each gate failure back in) → **a bigger local model** → **escalate to Claude**

Free rungs are exhausted before any paid work happens. You attach a **gate** so the local model can self-correct:

- **Structural gates** (cheap, content-free): `require_json`, `schema_keys`, `contains`, `regex`, `min_len`
- **Executable gate**: `check_command` — a shell command that sees the candidate at `$CANDIDATE_FILE` and exits `0` to pass (e.g. a linter or test)

With no gate, `iterate` runs a single local attempt and asks Claude to verify.

```text
# Generate boilerplate, gated by a linter — retries locally until ruff is happy
iterate(message="write a Python slugify() function",
        category="boilerplate",
        check_command="ruff check $CANDIDATE_FILE")

# Extract structured data, gated on valid JSON with required keys
iterate(message="extract name, email, company from this signature: ...",
        category="extract",
        require_json=true,
        schema_keys=["name", "email", "company"])

# Quick one-off to the local model, no iteration
chat(message="explain what this regex does: ^\\d{3}-\\d{4}$")
```

### Tools

| Tool | What it does |
|------|--------------|
| `iterate` | Offload a task with a gate; retries locally, then a bigger local model, then escalates to Claude |
| `chat` | Send a single prompt to the local model and get the response + token usage |
| `quick_test` | Run a canned diagnostic (`hello` / `math` / `creative` / `code_review`) to sanity-check the model |
| `list_models` | List loaded models with speed/quality descriptions and the active marker |
| `set_model` | Switch the active model at runtime by name or fuzzy fragment — no restart needed |
| `health_check` | Confirm the backend is reachable |
| `set_work_hours_guard` | Block large (>22 GB RAM) models Mon–Fri 8am–5pm MT to avoid swap thrashing |
| `get_config` | Show current config (URL, active model, guard state) — resource `config://settings` |

Inside Claude Code, the bundled slash commands give you `/switch-model` (interactive model picker) and `/mlx-help` (this reference).

### Configuration

Set as env vars in the MCP server entry (the installer scaffolds these):

| Variable | Default | Notes |
|----------|---------|-------|
| `MLX_BASE_URL` | `http://localhost:8080` | Backend `/v1` URL |
| `MLX_DEFAULT_MODEL` | _(empty)_ | Optional — auto-detected from `/v1/models` if unset |
| `MLX_API_KEY` | _(empty)_ | Optional, for secured backends |
| `MLX_TIMEOUT` | `30` | Request timeout in seconds |

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
