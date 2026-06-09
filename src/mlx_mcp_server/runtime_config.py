"""Persistent runtime configuration for mlx-mcp-server.

Stores the user's active model choice in ~/.config/mlx-mcp/active_model so that
set_model() changes survive Claude Code restarts without touching settings.json.
"""

import os
import shutil
import tempfile
from pathlib import Path

_CONFIG_DIR = Path.home() / ".config" / "mlx-mcp"
_MODEL_FILE = _CONFIG_DIR / "active_model"


def read_runtime_model() -> str:
    """Return the persisted active model name, or '' if none is set."""
    try:
        return _MODEL_FILE.read_text().strip()
    except FileNotFoundError:
        return ""


def write_runtime_model(model: str) -> None:
    """Persist the active model name. Pass '' to clear the override."""
    if not model:
        try:
            _MODEL_FILE.unlink()
        except FileNotFoundError:
            pass
        return

    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=_CONFIG_DIR, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(model)
        shutil.move(tmp, str(_MODEL_FILE))
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
