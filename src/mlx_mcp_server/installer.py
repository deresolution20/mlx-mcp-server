"""Installs the mlx MCP server config and (optionally) slash commands."""
import json
import os
import platform
import shutil
import tempfile
from pathlib import Path


def _claude_desktop_config_path() -> Path:
    """Return the path to the Claude Desktop config file."""
    system = platform.system()
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    elif system == "Linux":
        return Path.home() / ".config" / "claude" / "claude_desktop_config.json"
    elif system == "Windows":
        appdata = os.environ.get("APPDATA")
        if not appdata:
            raise RuntimeError(
                "APPDATA environment variable is not set — cannot locate Claude Desktop config on Windows."
            )
        return Path(appdata) / "Claude" / "claude_desktop_config.json"
    else:
        raise RuntimeError(f"Unsupported platform: {system}")


def _claude_code_config_path() -> Path:
    """Return the path to the Claude Code settings file."""
    return Path.home() / ".claude" / "settings.json"


def _bundled_commands_dir() -> Path:
    """Return the path to bundled slash-command files."""
    return Path(__file__).parent / "commands"


def _atomic_write(dest: Path, content: str) -> None:
    """Write content to dest atomically via a temp file."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dest.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
        shutil.move(tmp, dest)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def install_mcp_config(
    *,
    claude_code: bool,
    base_url: str,
    model: str,
    api_key: str,
    dry_run: bool,
) -> None:
    """Write the mlx MCP server entry into Claude Desktop or Claude Code settings."""
    config_path = _claude_code_config_path() if claude_code else _claude_desktop_config_path()

    config: dict = {}
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text())
        except json.JSONDecodeError as e:
            raise SystemExit(
                f"Existing config at {config_path} contains invalid JSON: {e}\n"
                "Fix or remove the file before re-running."
            ) from None

    env: dict[str, str] = {"MLX_BASE_URL": base_url}
    if model:
        env["MLX_DEFAULT_MODEL"] = model
    if api_key:
        env["MLX_API_KEY"] = api_key

    config.setdefault("mcpServers", {})["mlx"] = {
        "command": "mlx-mcp-server",
        "env": env,
    }

    output = json.dumps(config, indent=2)

    if dry_run:
        print(f"[dry-run] Would write MCP config → {config_path}\n")
        print(output)
        return

    _atomic_write(config_path, output)
    target = "Claude Code" if claude_code else "Claude Desktop"
    print(f"✅ MCP config     → {config_path}")
    print(f"   Restart {target} to apply.")


def install_commands(*, dest_dir: Path | None = None, dry_run: bool = False) -> None:
    """Copy slash-command markdown files to ~/.claude/commands/."""
    src_dir = _bundled_commands_dir()
    dest = dest_dir or (Path.home() / ".claude" / "commands")

    if not src_dir.exists():
        raise RuntimeError(f"Bundled commands directory not found: {src_dir}")

    files = list(src_dir.glob("*.md"))
    if not files:
        raise RuntimeError(f"No .md files found in {src_dir}")

    if dry_run:
        print(f"[dry-run] Would install {len(files)} slash command(s) → {dest}/")
        for f in sorted(files):
            print(f"   /{f.stem}")
        return

    dest.mkdir(parents=True, exist_ok=True)
    for src in sorted(files):
        _atomic_write(dest / src.name, src.read_text())
        print(f"✅ /{src.stem:<20} → {dest / src.name}")


def install(
    *,
    claude_code: bool,
    base_url: str,
    model: str,
    api_key: str,
    dry_run: bool,
    with_commands: bool = False,
) -> None:
    """Full install entry point. Writes the MCP config and, optionally, slash commands."""
    install_mcp_config(
        claude_code=claude_code,
        base_url=base_url,
        model=model,
        api_key=api_key,
        dry_run=dry_run,
    )
    if with_commands:
        install_commands(dry_run=dry_run)
