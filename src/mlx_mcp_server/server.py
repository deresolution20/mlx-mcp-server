import json
from typing import Literal

from mcp.server.fastmcp import FastMCP

from .client import LLMClient
from .config import load_config
from .gates import structural_gate, executable_gate
from .iterate import run_iterate
from .runtime_config import read_work_hours_guard, write_work_hours_guard

_config = load_config()
_client = LLMClient(_config)

_SERVER_INSTRUCTIONS = """\
Offload-first policy (token thrift). This server bridges to a LOCAL model that is
free and private. Before doing eligible work yourself or delegating it to a
subagent, route it through the `iterate` tool first:

- Offload by default: summarize, extract, classify, reformat; boilerplate and
  test stubs; single-file or single-function code review; simple refactors;
  explaining code or errors; first drafts you will polish.
- Use a gate so the local model can self-correct: structural (require_json /
  schema_keys / contains / regex / min_len) and/or executable (check_command,
  which sees the candidate at $CANDIDATE_FILE and exits 0 to pass). With no gate,
  `iterate` runs once and asks you to verify.
- Always pass a coarse `category` (review / boilerplate / summarize / extract /
  explain / other). Counts only are logged — never content.
- Keep on Claude: multi-file reasoning, architecture and judgment calls,
  tool-using work, and the live interactive reply. When `iterate` returns
  ESCALATE, take over.
"""

mcp = FastMCP("mlx-mcp-server", instructions=_SERVER_INSTRUCTIONS)

import json as _json
import os as _os
from datetime import datetime, timezone

_CALL_LOG_PATH = _os.path.expanduser("~/.omlx/mlx-call-log.jsonl")


def _append_call_log(model, category, prompt_tokens, completion_tokens, rounds=1, winning_rung="local"):
    """Append one numeric usage record per offload call. Best-effort; never raises.

    Records counts only — no prompt/response content. `rounds` is the number of
    local attempts made; `winning_rung` is one of local / local_big / escalated.
    """
    rec = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "model": model or "",
        "category": category or "other",
        "prompt_tokens": int(prompt_tokens or 0),
        "completion_tokens": int(completion_tokens or 0),
        "rounds": int(rounds or 1),
        "winning_rung": winning_rung or "local",
    }
    try:
        _os.makedirs(_os.path.dirname(_CALL_LOG_PATH), exist_ok=True)
        with open(_CALL_LOG_PATH, "a") as fh:
            fh.write(_json.dumps(rec) + "\n")
    except OSError:
        pass


def _model_description(model_id: str) -> str:
    """Return a one-liner description based on model name patterns."""
    m = model_id.lower()

    # DeepSeek Coder V2 Lite — MoE, speed king
    if "deepseek" in m and "lite" in m:
        return "⚡ Turbo — ~135 tok/s, instant subagent calls, quick lookups & boilerplate"

    # Qwen3-Coder family — newer, non-thinking, excellent quality
    if "qwen3" in m and "coder" in m:
        if "30b" in m or "a3b" in m:
            return "🧠 Quality — ~51 tok/s, best coding quality, MoE (3B active), no thinking mode"
        return "💻 Qwen3-Coder"

    # Qwen2.5-Coder family — reliable, no thinking mode
    if "qwen" in m and "coder" in m:
        if "7b" in m:
            return "⚡ Fast — ~80 tok/s, speed fallback, solid code quality"
        if "14b" in m:
            return "⚖️  Everyday — ~28 tok/s, reliable default for most coding tasks"
        if "32b" in m:
            return "🧠 Quality — ~19 tok/s, complex code & multi-file reasoning"

    # Gemma family — kept for reference, slower than Qwen3-Coder on this hardware
    if "gemma" in m:
        return "🤖 Gemma"

    # Generic fallbacks
    if "coder" in m:
        return "💻 Coding model"
    if "distilled" in m:
        return "🔮 Reasoning — distilled from large model"

    return "🤖 General purpose"

_BIG_MODEL_RAM_THRESHOLD_GB = 22  # models above this need dedicated RAM headroom


def _estimated_ram_gb(model_id: str) -> float:
    """Estimate RAM needed (GB) based on model name patterns."""
    m = model_id.lower()
    params = 0.0
    for tag, count in [
        ("72b", 72), ("35b", 35), ("32b", 32), ("27b", 27),
        ("14b", 14), ("9b", 9), ("7b", 7), ("3b", 3), ("1.5b", 1.5),
    ]:
        if tag in m:
            params = count
            break
    if not params:
        return 0.0
    bits = 4
    if "8bit" in m:
        bits = 8
    elif "6bit" in m:
        bits = 6
    elif "3bit" in m:
        bits = 3
    return (params * bits / 8) + 2  # +2 GB overhead


def _is_work_hours(_now=None) -> bool:
    """True when the guard is enabled AND it's Mon–Fri 8am–5pm Mountain Time.

    Off by default — each user opts in via set_work_hours_guard(True).
    _now is injectable for testing; omit in production.
    """
    if not read_work_hours_guard():
        return False  # guard disabled — allow all models any time
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        return False
    from datetime import datetime
    if _now is None:
        _now = datetime.now(ZoneInfo("America/Boise"))
    if _now.weekday() >= 5:  # Sat / Sun
        return False
    return 8 <= _now.hour < 17


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
    max_tokens: int = 1024,
    top_p: float = 1.0,
    top_k: int = 0,
    category: str = "other",
) -> str:
    """Send a message to the local LLM and return the response with token usage.

    category is a coarse task tag (review/boilerplate/summarize/extract/explain/other)
    used only for offload-savings metrics; no content is logged.
    """
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
    _append_call_log(
        model=result.model,
        category=category,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
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
async def iterate(
    message: str,
    category: str = "other",
    system_prompt: str = "",
    require_json: bool = False,
    schema_keys: list[str] | None = None,
    contains: str = "",
    regex: str = "",
    min_len: int = 0,
    check_command: str = "",
    max_local_rounds: int = 3,
    big_model: str = "",
    temperature: float = 0.7,
    max_tokens: int = 1024,
) -> str:
    """Offload a task to the local model and let it iterate until a gate passes.

    Spends free rungs first: active local model retries (feeding the gate's
    failure text back in) up to max_local_rounds, then optionally one attempt on
    a bigger local model (big_model), then escalates to Claude. Provide a gate so
    retries can improve — structural (require_json / schema_keys / contains /
    regex / min_len) and/or executable (check_command, a shell command that sees
    the candidate at $CANDIDATE_FILE and exits 0 to pass). With no gate it runs a
    single local attempt and asks Claude to verify. category is a coarse task tag
    for offload-savings metrics; no content is logged.
    """
    temperature = max(0.0, min(2.0, temperature))
    max_tokens = max(1, min(4096, max_tokens))
    max_local_rounds = max(1, min(5, max_local_rounds))

    _NO_THINK = (
        "You are a direct, concise assistant. "
        "Output ONLY your final answer. "
        "Never use phrases like 'Here\\'s a thinking process', 'Let me analyze', or numbered planning steps. "
        "Never explain your reasoning — just answer."
    )

    has_structural = bool(require_json or schema_keys or contains or regex or min_len)
    if check_command:
        def gate_fn(text):
            return executable_gate(text, check_command)
    elif has_structural:
        def gate_fn(text):
            return structural_gate(
                text,
                require_json=require_json,
                schema_keys=schema_keys,
                contains=(contains or None),
                regex=(regex or None),
                min_len=min_len,
            )
    else:
        gate_fn = None

    async def chat_fn(message, system_prompt=""):
        return await _client.chat(
            message=message,
            system_prompt=system_prompt or _NO_THINK,
            temperature=temperature,
            max_tokens=max_tokens,
            enable_thinking=False,
        )

    result = await run_iterate(
        chat_fn=chat_fn,
        message=message,
        system_prompt=system_prompt,
        gate_fn=gate_fn,
        max_local_rounds=max_local_rounds,
        big_model=big_model,
        set_model_fn=_client.set_model,
        get_model_fn=lambda: _client._runtime_model,
    )

    _append_call_log(
        model=result.model,
        category=category,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        rounds=result.rounds,
        winning_rung=result.winning_rung,
    )

    badge = f"🏠 LOCAL · {result.model}" if result.model else "🏠 LOCAL"
    if result.escalate:
        status = (
            "⚠️  ESCALATE TO CLAUDE — local rungs exhausted. "
            "Finish it yourself, re-delegate with sharper criteria, or try a bigger model.\n"
            f"Last gate failures:\n- " + "\n- ".join(result.history[-3:])
        )
    elif result.passed is None:
        status = "🔎 VERIFY ON CLAUDE — no gate was set, so check this before using it."
    else:
        status = f"✅ Gate passed on rung '{result.winning_rung}'."

    return (
        f"{badge}  ·  {result.rounds} round(s)\n\n"
        f"{result.content}\n\n"
        f"---\n{status}"
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
async def set_model(model_name: str, force: bool = False) -> str:
    """Switch the active model at runtime — no Claude Code restart needed.

    Accepts the full model name OR a case-insensitive fragment (fuzzy match).
    Changes persist across restarts via ~/.config/mlx-mcp/active_model.
    Pass an empty string to clear the override and fall back to auto-detection.

    Large models (>22 GB estimated RAM) are blocked during work hours (Mon–Fri
    8am–5pm Mountain Time) to prevent swap thrashing. Use force=True to bypass —
    e.g. after running /big-model to close other apps first.

    Examples:
      set_model("coder-14b")           # matches Qwen2.5-Coder-14B-Instruct-4bit
      set_model("6bit")                # matches Qwen2.5-Coder-32B-Instruct-6bit
      set_model("6bit", force=True)    # bypass work-hours guard (use after /big-model)
      set_model("")                    # clear override, fall back to auto-detect
    """
    if not model_name:
        _client.set_model("")
        return (
            "✅ Model override cleared.\n"
            "Will auto-detect from backend on next request.\n\n"
            "Tip: call list_models to see what's available."
        )

    # Fetch available models for fuzzy matching + confirmation display.
    try:
        models = await _client.list_models()
        model_ids = [m.id for m in models]
    except Exception:
        # Backend unreachable — set the name as-is and warn.
        _client.set_model(model_name)
        return (
            f"✅ Active model set to: {model_name}\n"
            "   (Could not reach backend to validate — double-check the name with list_models)"
        )

    # Resolve: exact match first, then case-insensitive substring match.
    resolved = model_name  # default: use as given
    if model_name not in model_ids:
        fragment = model_name.lower()
        matches = [mid for mid in model_ids if fragment in mid.lower()]
        if len(matches) == 1:
            resolved = matches[0]
        elif len(matches) > 1:
            options = "\n".join(f"  - {m}" for m in matches)
            return (
                f"⚠️  '{model_name}' matches {len(matches)} models — be more specific:\n{options}"
            )
        else:
            options = "\n".join(f"  - {mid}" for mid in model_ids)
            return (
                f"❌ No model matching '{model_name}' found.\n\n"
                f"Available models:\n{options}"
            )

    # Work-hours guard: warn before loading big models that will likely 507 or swap.
    ram_gb = _estimated_ram_gb(resolved)
    if ram_gb > _BIG_MODEL_RAM_THRESHOLD_GB and _is_work_hours() and not force:
        return (
            f"⏰  Work hours detected (8am–5pm MT, Mon–Fri)\n\n"
            f"   {resolved} needs ~{ram_gb:.0f} GB RAM.\n"
            f"   Loading during work hours risks a 507 or ~1–2 tok/s swap speed.\n\n"
            f"   Options:\n"
            f"   • /big-model                      close other apps first, then load cleanly\n"
            f"   • After 5pm MT / weekends          swap is acceptable for async use\n"
            f"   • set_model(\"{model_name}\", force=True)   load anyway, you've been warned"
        )

    _client.set_model(resolved)
    model_list = "\n".join(
        f"  {'→' if mid == resolved else ' '} {mid}"
        for mid in model_ids
    )
    suffix = f" (matched from '{model_name}')" if resolved != model_name else ""
    return (
        f"✅ Active model set to: {resolved}{suffix}\n"
        f"   Persisted to ~/.config/mlx-mcp/active_model\n\n"
        f"Available models:\n{model_list}"
    )


@mcp.tool()
def set_work_hours_guard(enabled: bool) -> str:
    """Enable or disable the work-hours guard for large models.

    When enabled, loading models that need >22 GB RAM is blocked Mon–Fri
    8am–5pm Mountain Time to prevent swap thrashing during work hours.

    Off by default — each team member opts in independently.
    The setting persists across restarts in ~/.config/mlx-mcp/work_hours_guard.

    Examples:
      set_work_hours_guard(True)   # protect work hours — use /big-model or wait until 5pm
      set_work_hours_guard(False)  # load any model any time (default)
    """
    write_work_hours_guard(enabled)
    if enabled:
        return (
            "✅ Work-hours guard enabled.\n"
            "   Large models (>22 GB) are blocked Mon–Fri 8am–5pm Mountain Time.\n"
            "   Use /big-model to close other apps and load them cleanly,\n"
            "   or load freely after 5pm / on weekends."
        )
    return (
        "✅ Work-hours guard disabled.\n"
        "   Any model can be loaded at any time."
    )


@mcp.tool()
async def health_check() -> str:
    """Check whether the configured LLM backend is reachable."""
    result = await _client.health_check()
    return json.dumps(result, indent=2)


@mcp.tool()
async def list_models() -> str:
    """List available models with descriptions and active marker.

    Use set_model("fragment") to switch — e.g. set_model("14b-4bit").
    Or use the /switch-model slash command for an interactive picker.
    """
    models = await _client.list_models()
    if not models:
        return "No models found. The backend may not support model listing."
    active = _client.get_active_model()
    lines = ["Local models (→ = active)\n"]
    for i, m in enumerate(models, 1):
        marker = "→" if m.id == active else " "
        desc = _model_description(m.id)
        lines.append(f"  {marker} {i}. {m.id}\n       {desc}")
    lines.append("\nSwitch: set_model(\"<name or fragment>\")  |  /switch-model for interactive picker")
    return "\n".join(lines)


@mcp.resource("config://settings")
def get_config() -> str:
    """Current server configuration (API key is not exposed)."""
    return json.dumps(
        {
            "base_url": _config.base_url,
            "active_model": _client.get_active_model(),
            "model_source": (
                "runtime (set_model)" if _client._runtime_model
                else "env var (MLX_DEFAULT_MODEL)" if _config.default_model
                else "auto-detect"
            ),
            "work_hours_guard": read_work_hours_guard(),
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
        "--with-commands",
        action="store_true",
        help="Also install slash commands (/switch-model, /big-model, /big-model-done) to ~/.claude/commands/",
    )
    install_parser.add_argument(
        "--with-scripts",
        action="store_true",
        help="Also install Big Model Mode shell scripts to ~/bin/",
    )
    install_parser.add_argument(
        "--with-offload",
        action="store_true",
        help="Also install the offload-first power-up: Claude Code hooks + /offload skill",
    )
    install_parser.add_argument(
        "--full",
        action="store_true",
        help="Equivalent to --with-commands --with-scripts --with-offload; installs everything",
    )
    install_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the config that would be written without modifying any files",
    )

    subparsers.add_parser("help", help="Show commands, MCP tools, and usage examples")

    args = parser.parse_args()

    if args.command == "install":
        import os as _os
        from .installer import install
        # Prefer env var over CLI flag so the key doesn't appear in shell history or ps output
        api_key = args.api_key or _os.environ.get("MLX_API_KEY", "")
        with_commands = args.with_commands or args.full
        with_scripts = args.with_scripts or args.full
        with_offload = args.with_offload or args.full
        install(
            claude_code=args.claude_code,
            base_url=args.base_url,
            model=args.model,
            api_key=api_key,
            dry_run=args.dry_run,
            with_commands=with_commands,
            with_scripts=with_scripts,
            with_offload=with_offload,
        )
    elif args.command == "help":
        _print_help()
    else:
        mcp.run()


def _print_help() -> None:
    print("""
mlx-mcp-server — local LLM bridge for Claude Code
===================================================

INSTALL SUBCOMMAND
  Wire up the MCP server, slash commands, and shell scripts in one step.

  Quick start (recommended):
    mlx-mcp-server install --claude-code --full

  Options:
    --claude-code        Target Claude Code (~/.claude/settings.json)
                         Omit to target Claude Desktop instead
    --base-url URL       oMLX base URL  (default: http://localhost:8080)
    --model NAME         Pin a default model  (auto-detected if omitted)
    --api-key KEY        API key for oMLX  (or set MLX_API_KEY env var)
    --with-commands      Install slash commands → ~/.claude/commands/
    --with-scripts       Install Big Model Mode scripts → ~/bin/
    --full               Install everything (--with-commands + --with-scripts)
    --dry-run            Preview what would be written without touching files

  Examples:
    # Full install for Claude Code
    mlx-mcp-server install --claude-code --full

    # Claude Desktop only, custom URL
    mlx-mcp-server install --base-url http://localhost:8000

    # Preview without writing
    mlx-mcp-server install --claude-code --full --dry-run

    # API key via env var (keeps key out of shell history)
    MLX_API_KEY=my-key mlx-mcp-server install --claude-code --full

──────────────────────────────────────────────────────────────

SLASH COMMANDS  (inside Claude Code, type /<name>)
  /switch-model      List all available models and switch to one interactively
  /big-model         Close RAM-heavy apps, load the 6-bit 32B model for max quality
  /big-model-done    Switch back to the fast 4-bit model and reopen all apps
  /mlx-help          Show this reference inside Claude Code

──────────────────────────────────────────────────────────────

MCP TOOLS  (Claude Code calls these automatically via the mlx server)
  chat                Send a prompt to the local LLM
                        chat(message="explain this function", system_prompt="be concise")

  quick_test          Run a canned test to verify the active model is responding
                        quick_test(test_type="code_review")
                        test_type options: hello | code_review | math

  list_models         List all models available in oMLX with descriptions
                        list_models()

  set_model           Switch the active model by name or fragment
                        set_model(model_name="14b")
                        set_model(model_name="Qwen2.5-Coder-32B-Instruct-6bit", force=True)

  health_check        Confirm oMLX is reachable and responding
                        health_check()

  get_config          Show current server config (URL, model, work-hours guard)
                        get_config()

  set_work_hours_guard  Toggle the work-hours guard on or off
                          set_work_hours_guard(enabled=True)   # block big models 8am-5pm MT
                          set_work_hours_guard(enabled=False)  # always allow

──────────────────────────────────────────────────────────────

MODEL LINEUP
  ⚡ DeepSeek-Coder-V2-Lite-Instruct-4bit-mlx   ~135 tok/s  turbo — quick lookups & boilerplate
  ⚡ Qwen2.5-Coder-7B-Instruct-4bit             ~80 tok/s   fast — speed fallback
  ⚖️  Qwen2.5-Coder-14B-Instruct-4bit            ~28 tok/s   everyday default
  🧠 Qwen3-Coder-30B-A3B-Instruct-MLX-4bit      ~51 tok/s   quality — best coding, MoE, no thinking mode

──────────────────────────────────────────────────────────────

MORE INFO
  GitHub:  https://github.com/deresolution20/mlx-mcp-server
  PyPI:    https://pypi.org/project/mlx-mcp-server/
""".strip())
