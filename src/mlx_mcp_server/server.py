import json
import sys
from typing import Literal

from mcp.server.fastmcp import FastMCP

from .client import LLMClient
from .config import load_config

_config = load_config()
_client = LLMClient(_config)

mcp = FastMCP("mlx-mcp-server")

_QUICK_TEST_PROMPTS: dict[str, str] = {
    "hello": "Say hello and introduce yourself briefly.",
    "math": "What is 347 × 28? Show your working.",
    "creative": "Write a two-sentence story about a robot who discovers music.",
    "code_review": "Review this Python snippet and suggest one improvement: `def f(x): return x*x`",
}


@mcp.tool()
async def chat(
    message: str,
    system_prompt: str = "",
    temperature: float = 0.7,
    max_tokens: int = 512,
    top_p: float = 1.0,
    top_k: int = 0,
) -> str:
    """Send a message to the local LLM and return the response with token usage."""
    result = await _client.chat(
        message=message,
        system_prompt=system_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
        top_p=top_p,
        top_k=top_k,
    )
    return (
        f"{result.content}\n\n"
        f"---\n"
        f"Tokens: {result.prompt_tokens} prompt + {result.completion_tokens} completion"
        f" = {result.total_tokens} total | {result.elapsed_seconds:.2f}s"
    )


@mcp.tool()
async def quick_test(
    test_type: Literal["hello", "math", "creative", "code_review"],
) -> str:
    """Run a predefined diagnostic prompt to sanity-check the loaded model."""
    prompt = _QUICK_TEST_PROMPTS[test_type]
    result = await _client.chat(message=prompt, temperature=0.7, max_tokens=256)
    tok_per_sec = (
        result.completion_tokens / result.elapsed_seconds
        if result.elapsed_seconds > 0
        else 0.0
    )
    return (
        f"Test: {test_type}\n"
        f"Prompt: {prompt}\n\n"
        f"Response:\n{result.content}\n\n"
        f"---\n"
        f"Latency: {result.elapsed_seconds:.2f}s | "
        f"Completion tokens: {result.completion_tokens} | "
        f"Speed: {tok_per_sec:.1f} tok/s"
    )


@mcp.tool()
async def health_check() -> str:
    """Check whether the configured LLM backend is reachable."""
    result = await _client.health_check()
    return json.dumps(result, indent=2)


@mcp.tool()
async def list_models() -> str:
    """List available models on the configured backend."""
    models = await _client.list_models()
    if not models:
        return "No models found. The backend may not support model listing."
    return "\n".join(f"- {m.id}" for m in models)


@mcp.resource("config://settings")
def get_config() -> str:
    """Current server configuration (API key is not exposed)."""
    return json.dumps(
        {
            "base_url": _config.base_url,
            "default_model": _config.default_model or "(none — backend decides)",
            "timeout_seconds": _config.timeout,
        },
        indent=2,
    )


@mcp.resource("docs://usage")
def get_usage_docs() -> str:
    """Setup and usage documentation."""
    return """\
# mlx-mcp-server Usage

## Starting your LLM backend

### MLX LM (Apple Silicon — recommended)
```bash
pip install mlx-lm
mlx_lm.server --model mlx-community/Mistral-7B-Instruct-v0.3-4bit
```
Server starts on http://localhost:8080

### Ollama (Intel Mac / Linux)
```bash
ollama serve
ollama pull mistral
```
Set `MLX_BASE_URL=http://localhost:11434` and `MLX_DEFAULT_MODEL=mistral`

## Available Tools

- `chat` — Send a message to the local model
- `quick_test` — Run a diagnostic (hello/math/creative/code_review)
- `health_check` — Verify the backend is reachable
- `list_models` — List loaded models

## Configuration (env vars in Claude Desktop config)

| Variable | Default | Notes |
|----------|---------|-------|
| MLX_BASE_URL | http://localhost:8080 | Backend URL |
| MLX_DEFAULT_MODEL | (empty) | Required for Ollama |
| MLX_API_KEY | (empty) | Optional, for secured backends |
| MLX_TIMEOUT | 30 | Request timeout in seconds |
"""


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(prog="mlx-mcp-server")
    subparsers = parser.add_subparsers(dest="command")

    install_parser = subparsers.add_parser(
        "install", help="Auto-configure Claude Desktop or Claude Code"
    )
    install_parser.add_argument(
        "--claude-code",
        action="store_true",
        help="Target Claude Code (~/.claude/settings.json) instead of Claude Desktop",
    )
    install_parser.add_argument(
        "--base-url",
        default="http://localhost:8080",
        metavar="URL",
        help="Value for MLX_BASE_URL (default: http://localhost:8080)",
    )
    install_parser.add_argument(
        "--model",
        default="",
        metavar="NAME",
        help="Value for MLX_DEFAULT_MODEL (required for Ollama)",
    )
    install_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the config that would be written without modifying any files",
    )

    args = parser.parse_args()

    if args.command == "install":
        from .installer import install
        install(
            claude_code=args.claude_code,
            base_url=args.base_url,
            model=args.model,
            dry_run=args.dry_run,
        )
    else:
        mcp.run()
