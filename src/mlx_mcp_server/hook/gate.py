"""PreToolUse decision core: softly flag a large write with no local offload this turn.

Never raises, never blocks: returns a non-blocking allow+reason on a miss, else None.
"""
import json
import os
import sys

from . import logs, turnstate

LARGE_CHARS = 1200


def written_size(tool_name, tool_input):
    if not tool_input:
        return 0
    try:
        if tool_name == "Write":
            return len(tool_input.get("content", ""))
        if tool_name == "Edit":
            return len(tool_input.get("new_string", ""))
        if tool_name == "MultiEdit":
            return sum(len(e.get("new_string", "")) for e in tool_input.get("edits", []))
        return 0
    except Exception:  # noqa: BLE001 - never raise
        return 0


def category_for(tool_input):
    if not tool_input:
        return "other"
    try:
        ext = os.path.splitext(tool_input.get("file_path", ""))[1][1:].lower()
        if ext in ("py", "js", "ts", "tsx", "go", "rs", "java", "c", "cpp", "rb", "sh"):
            return "code"
        if ext in ("md", "txt", "rst"):
            return "docs"
        return "other"
    except Exception:  # noqa: BLE001
        return "other"


def offloaded_since(ts, *, call_log_path):
    if not ts or not call_log_path:
        return False
    try:
        with open(call_log_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if "ts" in obj and obj["ts"] >= ts:
                        return True
                except Exception:  # noqa: BLE001
                    continue
        return False
    except Exception:  # noqa: BLE001
        return False


def evaluate(event, *, started_ts_fn, offloaded_fn, append_decision_fn):
    try:
        tool_name = event.get("tool_name", "")
        tool_input = event.get("tool_input", {})
        if written_size(tool_name, tool_input) < LARGE_CHARS:
            return None
        ts = started_ts_fn()
        if not ts:
            return None
        if offloaded_fn(ts):
            return None
        append_decision_fn("missed_offload", category_for(tool_input), 0.0)
        return {"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "permissionDecisionReason": "⚠️ Large generation written with nothing "
            "offloaded to local this turn — route offloadable work through iterate.",
        }}
    except Exception:  # noqa: BLE001 - a gate must never break a tool call
        return None


def main():
    try:
        event = json.load(sys.stdin)
    except Exception:  # noqa: BLE001
        return 0
    out = evaluate(
        event,
        started_ts_fn=turnstate.started_ts,
        offloaded_fn=lambda ts: offloaded_since(ts, call_log_path=logs.CALL_LOG_PATH),
        append_decision_fn=logs.append_decision,
    )
    if out:
        sys.stdout.write(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
