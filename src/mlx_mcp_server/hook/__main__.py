"""Entry point wired as a UserPromptSubmit hook. Reads the event JSON on stdin,
emits an optional context-injection JSON on stdout. Always exits 0.

Also stamps the turn-start timestamp (for the offload gate) and, when the day has
recorded missed offloads, appends a nudge to the injected context.
"""
import json
import sys
from datetime import datetime, timezone

from . import logs, turnstate
from .run import run, _inject


def _nudge_text():
    today = datetime.now(timezone.utc).date().isoformat()
    c = logs.decisions_today(today)
    miss, off = c.get("missed_offload", 0), c.get("offloaded", 0)
    if miss <= 0:
        return None
    return (f"Offload status today: {off} offloaded, {miss} missed-offload write(s). "
            "Route offloadable generation (boilerplate, drafts, summaries, single-file "
            "code) through the local model via iterate before writing it.")


def main():
    try:
        event = json.load(sys.stdin)
    except Exception:  # noqa: BLE001
        return 0
    try:
        turnstate.stamp(datetime.now(timezone.utc).isoformat())
    except Exception:  # noqa: BLE001
        pass
    out = run(event)
    nudge = _nudge_text()
    if nudge:
        if out and "hookSpecificOutput" in out:
            out["hookSpecificOutput"]["additionalContext"] += "\n\n" + nudge
        else:
            out = _inject(nudge)
    if out:
        sys.stdout.write(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
