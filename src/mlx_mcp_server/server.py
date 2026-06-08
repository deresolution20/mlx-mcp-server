import json
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
    # Clamp parameters to safe ranges to prevent resource exhaustion
    temperature = max(0.0, min(2.0, temperature))
    max_tokens = max(1, min(4096, max_tokens))
    top_p = max(0.0, min(1.0, top_p))
    top_k = max(0, min(200, top_k))

    _NO_THINK = (
        "You are a direct, concise assistant. "
        "Output ONLY your final answer. "
        "Never use phrases like 'Here\\'s a thinking process', 'Let me analyze', or numbered planning steps. "
        "Never explain your reasoning — just answer."
    )
    result = await _client.chat(
        message=message,
        system_prompt=system_prompt or _NO_THINK,
        temperature=temperature,
        max_tokens=max_tokens,
        top_p=top_p,
        top_k=top_k,
        enable_thinking=False,
    )
    badge = f"🏠 LOCAL · {result.model}" if result.model else "🏠 LOCAL"
    return (
        f"{badge}\n\n"
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
    _NO_THINK = (
        "You are a direct, concise assistant. "
        "Output ONLY your final answer. "
        "Never use phrases like 'Here\\'s a thinking process', 'Let me analyze', or numbered planning steps. "
        "Never explain your reasoning — just answer."
    )
    result = await _client.chat(
        message=prompt,
        system_prompt=_NO_THINK,
        temperature=0.7,
        max_tokens=1024,
        enable_thinking=False,
    )
    tok_per_sec = (
        result.completion_tokens / result.elapsed_seconds
        if result.elapsed_seconds > 0
        else 0.0
    )
    badge = f"🏠 LOCAL · {result.model}" if result.model else "🏠 LOCAL"
    return (
        f"Test: {test_type}\n"
        f"Prompt: {prompt}\n\n"
        f"Response:\n{result.content}\n\n"
        f"---\n"
        f"{badge} · {tok_per_sec:.1f} tok/s · {result.completion_tokens} tokens · {result.elapsed_seconds:.2f}s"
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
| MLX_DEFAULT_MODEL | (empty) | Optional — auto-detected from /v1/models if not set |
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
        help="Value for MLX_DEFAULT_MODEL (optional — auto-detected from /v1/models if not set)",
    )
    install_parser.add_argument(
        "--api-key",
        default="",
        metavar="KEY",
        help=(
            "Value for MLX_API_KEY (required for oMLX and other secured backends). "
            "Tip: set MLX_API_KEY in your environment instead to keep the key out of shell history."
        ),
    )
    install_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the config that would be written without modifying any files",
    )

    args = parser.parse_args()

    if args.command == "install":
        import os as _os
        from .installer import install
        # Prefer env var over CLI flag so the key doesn't appear in shell history or ps output
        api_key = args.api_key or _os.environ.get("MLX_API_KEY", "")
        install(
            claude_code=args.claude_code,
            base_url=args.base_url,
            model=args.model,
            api_key=api_key,
            dry_run=args.dry_run,
        )
    else:
        mcp.run()
