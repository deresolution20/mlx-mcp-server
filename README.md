# mlx-mcp-server

MCP server bridging Claude Code and Claude Desktop to a locally-running LLM. Optimized for [MLX LM](https://github.com/ml-explore/mlx-lm) on Apple Silicon, with support for any OpenAI-compatible backend (Ollama, LM Studio, etc.).

## Install

```bash
pip install mlx-mcp-server
```

## Setup

**1. Start your local LLM**

```bash
# Apple Silicon — MLX LM
mlx_lm.server --model mlx-community/Mistral-7B-Instruct-v0.3-4bit

# Intel Mac / Linux — Ollama
ollama serve && ollama pull mistral
```

**2. Add to Claude Desktop**

```bash
# MLX (Apple Silicon)
mlx-mcp-server install

# Ollama
mlx-mcp-server install --base-url http://localhost:11434 --model mistral

# Preview before writing
mlx-mcp-server install --dry-run
```

**3. Add to Claude Code**

```bash
mlx-mcp-server install --claude-code
```

Restart Claude Desktop / Claude Code after installing.

## Tools

| Tool | Description |
|------|-------------|
| `chat` | Send a message to your local model |
| `quick_test` | Run a diagnostic: `hello`, `math`, `creative`, or `code_review` |
| `health_check` | Check if the backend is reachable |
| `list_models` | List available models on the backend |

## Configuration

Set via environment variables (or the `install` command sets them automatically):

| Variable | Default | Description |
|----------|---------|-------------|
| `MLX_BASE_URL` | `http://localhost:8080` | Backend URL |
| `MLX_DEFAULT_MODEL` | `""` | Model name — required for Ollama |
| `MLX_API_KEY` | `""` | API key for secured backends |
| `MLX_TIMEOUT` | `30` | Request timeout in seconds |

## Manual Claude Desktop config

If you prefer to edit the config file directly (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS):

```json
{
  "mcpServers": {
    "mlx": {
      "command": "mlx-mcp-server",
      "env": {
        "MLX_BASE_URL": "http://localhost:8080",
        "MLX_DEFAULT_MODEL": ""
      }
    }
  }
}
```

## Requirements

- Python 3.11+
- A running OpenAI-compatible LLM backend:
  - [MLX LM](https://github.com/ml-explore/mlx-lm) (Apple Silicon, recommended)
  - [Ollama](https://ollama.ai) (Intel Mac / Linux)
  - [LM Studio](https://lmstudio.ai) or any other OpenAI-compatible server

## License

MIT
