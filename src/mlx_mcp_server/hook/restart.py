"""Case 2 recovery: attempt `omlx restart`, then report health / diagnose."""
import json
import subprocess
import urllib.request
from dataclasses import dataclass


@dataclass
class RestartOutcome:
    """Result of an oMLX restart attempt."""
    healthy: bool
    detail: str


def _default_health(base_url):
    """Default health probe against a base_url."""
    try:
        with urllib.request.urlopen(base_url.rstrip("/") + "/health", timeout=5) as r:
            return json.loads(r.read().decode()).get("status") == "healthy"
    except Exception:
        return False


def restart_omlx(base_url, *, run_fn=subprocess.run, health_fn=_default_health):
    """Run `omlx restart`, poll health once; if still down, capture `omlx diagnose`.
    Never raises."""
    try:
        run_fn(["omlx", "restart"], capture_output=True, text=True, timeout=15)
    except Exception as e:  # noqa: BLE001 - best-effort recovery, must not raise
        return RestartOutcome(False, f"`omlx restart` failed to run: {e}")
    if health_fn(base_url):
        return RestartOutcome(True, "oMLX is healthy again after restart.")
    try:
        diag = run_fn(["omlx", "diagnose"], capture_output=True, text=True, timeout=15)
        detail = (getattr(diag, "stdout", "") or getattr(diag, "stderr", "") or "").strip()
    except Exception as e:  # noqa: BLE001
        detail = f"`omlx diagnose` failed: {e}"
    return RestartOutcome(False, detail[:1500] or "still down; no diagnose output")
