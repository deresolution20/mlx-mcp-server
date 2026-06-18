"""Stage 4: append counts-only records. Never stores prompt/response text."""
import json
import os
from datetime import datetime, timezone

CALL_LOG_PATH = os.path.expanduser("~/.omlx/mlx-call-log.jsonl")
DECISIONS_PATH = os.path.expanduser("~/.omlx/hook-decisions.jsonl")
DECISIONS = {"offloaded", "passthrough", "gate_escalate", "infra_error", "missed_offload"}


def _now():
    """Current UTC timestamp as an ISO string."""
    return datetime.now(timezone.utc).isoformat()


def _append(path, rec):
    """Append a JSON record as one line to a file, best-effort."""
    try:
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(path, "a") as fh:
            fh.write(json.dumps(rec) + "\n")
    except OSError:
        pass


def append_call_log(model, category, prompt_tokens, completion_tokens, *,
                    rounds=1, path=CALL_LOG_PATH, now_fn=_now):
    """Same schema as server._append_call_log so the savings panel reads it."""
    _append(path, {
        "ts": now_fn(),
        "model": model or "",
        "category": category or "other",
        "prompt_tokens": int(prompt_tokens or 0),
        "completion_tokens": int(completion_tokens or 0),
        "rounds": int(rounds or 1),
        "winning_rung": "local",
    })


def append_decision(decision, category, confidence, *,
                    path=DECISIONS_PATH, now_fn=_now):
    """Counts-only routing decision for capture/escalation panels."""
    _append(path, {
        "ts": now_fn(),
        "decision": decision,
        "category": category or "other",
        "confidence": round(float(confidence or 0.0), 3),
    })


def decisions_today(date_prefix, *, path=DECISIONS_PATH):
    """Counts-only {decision: n} for ts starting with date_prefix. Never raises."""
    out = {}
    try:
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    o = json.loads(line)
                except ValueError:
                    continue
                if str(o.get("ts", "")).startswith(date_prefix):
                    d = o.get("decision", "")
                    out[d] = out.get(d, 0) + 1
    except OSError:
        pass
    return out
