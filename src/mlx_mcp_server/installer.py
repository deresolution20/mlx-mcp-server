import json
import os
import platform
import shutil
import tempfile
from pathlib import Path


def _claude_desktop_config_path() -> Path:
    system = platform.system()
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    elif system == "Linux":
        return Path.home() / ".config" / "claude" / "claude_desktop_config.json"
    elif system == "Windows":
        appdata = os.environ.get("APPDATA", "")
        return Path(appdata) / "Claude" / "claude_desktop_config.json"
    else:
        raise RuntimeError(f"Unsupported platform: {system}")


def _claude_code_config_path() -> Path:
    return Path.home() / ".claude" / "settings.json"


def install(*, claude_code: bool, base_url: str, model: str, api_key: str, dry_run: bool) -> None:
    config_path = _claude_code_config_path() if claude_code else _claude_desktop_config_path()

    config: dict = {}
    if config_path.exists():
        config = json.loads(config_path.read_text())

    env: dict[str, str] = {
        "MLX_BASE_URL": base_url,
        "MLX_DEFAULT_MODEL": model,
    }
    if api_key:
        env["MLX_API_KEY"] = api_key

    config.setdefault("mcpServers", {})["mlx"] = {
        "command": "mlx-mcp-server",
        "env": env,
    }

    output = json.dumps(config, indent=2)

    if dry_run:
        print(f"Dry run — would write to: {config_path}\n")
        print(output)
        return

    config_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=config_path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(output)
        shutil.move(tmp, config_path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise

    target = "Claude Code" if claude_code else "Claude Desktop"
    print(f"Added mlx-mcp-server to {target} config: {config_path}")
    print(f"Restart {target} to apply changes.")
