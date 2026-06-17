# Internal Tool-Loop Offload (Phase 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** A soft `PreToolUse` gate that flags large code/doc writes with no local offload that turn, a turn-boundary stamp + nudge on the existing `UserPromptSubmit` hook, and dashboard panels for local-generation share + missed offloads.

**Architecture:** Two cooperating pure-stdlib hooks share `~/.omlx/turn-state.json`. The prompt hook stamps turn start + nudges; the new `mlx-offload-gate` PreToolUse hook detects misses and logs counts-only `missed_offload`. token-metrics gets two panels over already-collected data.

**Tech Stack:** Python 3.11+, stdlib only. Reuses `logs.append_decision`, `logs.CALL_LOG_PATH`, `logs.DECISIONS`.

## Global Constraints

- **Pure stdlib** in all `hook/` modules. **Never raises, never blocks** (gate always returns allow or None). Counts/labels only — no code/path/prompt text in any log.
- `missed_offload` decision schema = existing `{ts, decision, category, confidence}`; `category` ∈ `code|docs|other` (from file extension only).
- `LARGE_CHARS = 1200`. Tests in `tests/test_hook_turnstate.py`, `tests/test_hook_gate.py`. Run `uv run pytest`.
- The gate does **no network calls**. The nudge only nags when ≥1 `missed_offload` exists today (otherwise silent).
- Console script wiring is manual (installer never edits `settings.json`).

---

### Task 1: `turnstate.py` (turn-boundary marker)

**Files:** Create `src/mlx_mcp_server/hook/turnstate.py`, Test `tests/test_hook_turnstate.py`

**Produces:** `TURN_STATE_PATH`, `stamp(ts, *, path=TURN_STATE_PATH)`, `started_ts(*, path=TURN_STATE_PATH) -> str|None`.

- [ ] **Step 1: Failing tests**

```python
# tests/test_hook_turnstate.py
from mlx_mcp_server.hook import turnstate


def test_stamp_then_read_roundtrip(tmp_path):
    p = str(tmp_path / "ts.json")
    turnstate.stamp("2026-06-17T22:00:00+00:00", path=p)
    assert turnstate.started_ts(path=p) == "2026-06-17T22:00:00+00:00"


def test_missing_file_returns_none(tmp_path):
    assert turnstate.started_ts(path=str(tmp_path / "nope.json")) is None


def test_garbage_returns_none(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json")
    assert turnstate.started_ts(path=str(p)) is None


def test_stamp_never_raises_on_bad_path():
    turnstate.stamp("x", path="/nonexistent-root/cannot/write.json")  # no exception
```

- [ ] **Step 2: Run, verify fail** — `uv run pytest tests/test_hook_turnstate.py -v`

- [ ] **Step 3: Implement** (drafted on the local 30B, py_compile-gated, verified here; unused `datetime` import removed)

```python
# src/mlx_mcp_server/hook/turnstate.py
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
```

- [ ] **Step 4: Run, verify pass.** **Step 5: Commit** `feat(hook): turn-state marker`.

---

### Task 2: `gate.py` decision core

**Files:** Create `src/mlx_mcp_server/hook/gate.py`, Test `tests/test_hook_gate.py`

**Produces:** `LARGE_CHARS`, `written_size(tool_name, tool_input)`, `category_for(tool_input)`, `offloaded_since(ts, *, call_log_path)`, `evaluate(event, *, started_ts_fn, offloaded_fn, append_decision_fn) -> dict|None`, and `main()` (Task 3).

- [ ] **Step 1: Failing tests**

```python
# tests/test_hook_gate.py
from mlx_mcp_server.hook import gate

BIG = "x" * 1300
SMALL = "x" * 10


def test_written_size_shapes():
    assert gate.written_size("Write", {"content": BIG}) == 1300
    assert gate.written_size("Edit", {"new_string": "abc"}) == 3
    assert gate.written_size("MultiEdit", {"edits": [{"new_string": "ab"}, {"new_string": "cd"}]}) == 4
    assert gate.written_size("Read", {"content": BIG}) == 0
    assert gate.written_size("Write", None) == 0


def test_category_for():
    assert gate.category_for({"file_path": "a/b.py"}) == "code"
    assert gate.category_for({"file_path": "README.md"}) == "docs"
    assert gate.category_for({"file_path": "data.csv"}) == "other"
    assert gate.category_for({}) == "other"


def test_offloaded_since(tmp_path):
    p = tmp_path / "call.jsonl"
    p.write_text('{"ts": "2026-06-17T21:00:00"}\n{"ts": "2026-06-17T23:00:00"}\n')
    assert gate.offloaded_since("2026-06-17T22:00:00", call_log_path=str(p)) is True
    assert gate.offloaded_since("2026-06-18T00:00:00", call_log_path=str(p)) is False
    assert gate.offloaded_since("2026-06-17T22:00:00", call_log_path=str(tmp_path / "missing")) is False


def test_evaluate_flags_miss():
    logged = []
    out = gate.evaluate(
        {"tool_name": "Write", "tool_input": {"content": BIG, "file_path": "x.py"}},
        started_ts_fn=lambda: "2026-06-17T22:00:00",
        offloaded_fn=lambda ts: False,
        append_decision_fn=lambda d, c, conf: logged.append((d, c, conf)),
    )
    assert out["hookSpecificOutput"]["permissionDecision"] == "allow"
    assert "iterate" in out["hookSpecificOutput"]["permissionDecisionReason"]
    assert logged == [("missed_offload", "code", 0.0)]


def test_evaluate_silent_on_small_write():
    assert gate.evaluate(
        {"tool_name": "Write", "tool_input": {"content": SMALL, "file_path": "x.py"}},
        started_ts_fn=lambda: "t", offloaded_fn=lambda ts: False,
        append_decision_fn=lambda *a: None) is None


def test_evaluate_silent_when_offloaded_this_turn():
    assert gate.evaluate(
        {"tool_name": "Write", "tool_input": {"content": BIG, "file_path": "x.py"}},
        started_ts_fn=lambda: "t", offloaded_fn=lambda ts: True,
        append_decision_fn=lambda *a: None) is None


def test_evaluate_silent_when_turn_unknown():
    assert gate.evaluate(
        {"tool_name": "Write", "tool_input": {"content": BIG, "file_path": "x.py"}},
        started_ts_fn=lambda: None, offloaded_fn=lambda ts: False,
        append_decision_fn=lambda *a: None) is None


def test_evaluate_never_raises_on_garbage():
    assert gate.evaluate({}, started_ts_fn=lambda: "t",
                         offloaded_fn=lambda ts: False, append_decision_fn=lambda *a: None) is None
```

- [ ] **Step 2: Run, verify fail.**

- [ ] **Step 3: Implement** (drafted on the local 30B, py_compile-gated, verified here)

```python
# src/mlx_mcp_server/hook/gate.py  (decision core; main() added in Task 3)
"""PreToolUse decision core: softly flag a large write with no local offload this turn."""
import json
import os

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
```

- [ ] **Step 4: Run, verify pass.** **Step 5: Commit** `feat(hook): offload-gate decision core`.

---

### Task 3: gate entry point + console script

**Files:** Modify `src/mlx_mcp_server/hook/gate.py` (add `main`), `pyproject.toml` (script + version 0.4.0 → 0.5.0)

**Consumes:** `logs.append_decision`, `logs.CALL_LOG_PATH`, `turnstate.started_ts`.

- [ ] **Step 1: Add `main` to `gate.py`**

```python
import sys  # add to imports

from . import logs, turnstate  # add below stdlib imports


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
```

- [ ] **Step 2:** In `pyproject.toml [project.scripts]` add `mlx-offload-gate = "mlx_mcp_server.hook.gate:main"`; bump `version = "0.5.0"`.

- [ ] **Step 3: Commit** `feat(hook): mlx-offload-gate console script; v0.5.0`.

---

### Task 4: `missed_offload` decision + turn stamp & nudge on the prompt hook

**Files:** Modify `src/mlx_mcp_server/hook/logs.py` (DECISIONS), `src/mlx_mcp_server/hook/__main__.py` (stamp + nudge), Test `tests/test_hook_entrypoint.py` (add cases)

- [ ] **Step 1:** In `logs.py`, change `DECISIONS = {"offloaded", "passthrough", "gate_escalate", "infra_error"}` to add `"missed_offload"`.

- [ ] **Step 2:** Add a counts helper to `logs.py`:

```python
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
```

- [ ] **Step 3:** Modify `__main__.py` `main()` to stamp turn-state and append a nudge only when there were missed offloads today:

```python
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
```

- [ ] **Step 4: Tests** (add to `tests/test_hook_entrypoint.py` or new `tests/test_hook_nudge.py`): `decisions_today` filters by prefix; `_nudge_text` returns None when no misses and a string when misses exist (monkeypatch `logs.decisions_today`). Keep existing entrypoint tests green.

- [ ] **Step 5: Commit** `feat(hook): missed_offload decision + turn stamp & nudge`.

---

### Task 5: token-metrics dashboard panels

**Files:** Modify `token-metrics/dashboard/build_dashboard.py` + regenerate `token-savings.json`, Test `token-metrics/tests/test_dashboard.py`

**Note:** `exporter.py` already passes every decision through `mlx_hook_decision_total` (no allowlist), so `missed_offload` flows automatically — no exporter change.

- [ ] **Step 1:** Add two panels to the "Offload Capture" row:
  - **Local generation share** (stat/gauge, 0-1):
    `sum(mlx_offload_completion_tokens_total) / (sum(mlx_offload_completion_tokens_total) + sum(claude_tokens_total{kind="output"}))`
  - **Missed offloads** (stat/timeseries): `sum(mlx_hook_decision_total{decision="missed_offload"})`

- [ ] **Step 2:** Regenerate the dashboard JSON (run `build_dashboard.py`). Update `tests/test_dashboard.py` row/title assertions (relax counts, assert the two new titles present).

- [ ] **Step 3: Commit** `feat(dashboard): local-generation-share + missed-offloads panels`.

---

## Post-implementation (controller)

- `uv run pytest -q` in both repos green.
- `uv tool install --reinstall .` so `mlx-offload-gate` lands on PATH.
- Merge `tool-loop-offload-phase2` → main (mlx-mcp-server) and the token-metrics branch.
- **Push to GitHub + publish 0.5.0 to PyPI** (standing rule: GitHub and PyPI stay in lockstep).
- Give Brice the manual `settings.json` snippet for the `PreToolUse` matcher (`Write|Edit|MultiEdit` → `mlx-offload-gate`); restart Claude Code.
