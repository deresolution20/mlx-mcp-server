"""Track the current assistant turn's start timestamp for the offload gate."""
import json
import os

TURN_STATE_PATH = os.path.expanduser("~/.omlx/turn-state.json")


def stamp(ts, *, path=TURN_STATE_PATH):
    """Write the turn-start timestamp. Best-effort: never raises."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump({"turn_started_ts": ts}, f)
    except (OSError, TypeError, ValueError):
        pass


def started_ts(*, path=TURN_STATE_PATH):
    """Return the stored turn-start timestamp, or None. Never raises."""
    try:
        with open(path) as f:
            return json.load(f).get("turn_started_ts")
    except (OSError, ValueError, TypeError):
        return None
