# Case-2 Live Drill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A one-shot, on-demand drill that forces a real oMLX outage, drives the live `mlx-offload-hook`, asserts the full Case-2 path (detect → real `omlx restart` → recover → inject PAUSE → log `infra_error`), and leaves oMLX healthy with a backstop.

**Architecture:** A pure-stdlib, dependency-injected module `hook/drill.py` exposing `run_drill(...)` (DI: `health_fn`, `run_fn`, `hook_fn`, `decisions_path`) returning a `DrillResult`, plus a thin `main()` that wires real defaults, prints a report, and maps the result to an exit code (0 PASS / 1 FAIL / 2 abort). Shipped as console script `mlx-case2-drill`.

**Tech Stack:** Python 3, standard library only (`json`, `os`, `subprocess`, `dataclasses`). Reuses existing hook helpers: `omlx.resolve_omlx`, `restart._default_health`, `logs.append_decision`, `logs.DECISIONS_PATH`.

## Global Constraints

- **Pure stdlib only** in `hook/drill.py` — no third-party imports (matches the rest of `hook/`).
- **Never raises uncaught** — all orchestration in try/except/finally; the `finally` always attempts to confirm/restore oMLX health.
- **Reuse, don't reinvent oMLX-talking code** — health via `restart._default_health`; base URL via `omlx.resolve_omlx`; decision log path via `logs.DECISIONS_PATH`.
- **Privacy:** the drill only reads counts/labels from `hook-decisions.jsonl`; the allowed key set for an `infra_error` line is exactly `{"ts", "decision", "category", "confidence"}` — a line with any other key fails the privacy assertion.
- **Exit codes:** PASS = 0, FAIL = 1, pre-check abort = 2.
- **No live oMLX in the test suite** — all subprocess / health / hook calls are injected fakes.
- **Tests** live in `tests/test_hook_drill.py` (mirrors `tests/test_hook_restart.py`). Run with `uv run pytest`.
- The fixed drill prompt must clear the prefilter: ≥ 40 chars, not a control word.

---

### Task 1: Drill orchestrator (`hook/drill.py`)

**Files:**
- Create: `src/mlx_mcp_server/hook/drill.py`
- Test: `tests/test_hook_drill.py`

**Interfaces:**
- Consumes (existing): `mlx_mcp_server.hook.logs.append_decision(decision, category, confidence, *, path=...)`, `logs.DECISIONS_PATH`.
- Produces (for Task 2):
  - `@dataclass DrillResult(passed: bool, aborted: bool, steps: list, captured_directive: str, detail: str)` — `steps` is a list of `(name: str, ok: bool, detail: str)` tuples.
  - `DRILL_PROMPT: str` — the fixed offloadable prompt.
  - `ALLOWED_DECISION_KEYS: set[str]`.
  - `extract_context(stdout: str) -> str` — pulls `hookSpecificOutput.additionalContext` from hook stdout, `""` on any failure.
  - `run_drill(base_url, *, health_fn, run_fn, hook_fn, decisions_path, prompt=DRILL_PROMPT) -> DrillResult`. `hook_fn(stdin_text: str) -> (stdout: str, exit_code: int)`. `run_fn` matches `subprocess.run` signature.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_hook_drill.py
import json
import pytest
from mlx_mcp_server.hook import drill, logs

DIRECTIVE_OK = json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit",
        "additionalContext": (
            "⚠️ oMLX errored on an offloadable prompt. Restart attempted — "
            "oMLX is healthy again.\n\nDo NOT silently proceed on Opus for this. "
            "Tell Brice ... and PAUSE for his call."
        ),
    }
})


def _health_seq(seq):
    """Return a health_fn returning scripted bools, holding the last value."""
    state = {"i": 0}
    def health(_base_url):
        i = state["i"]
        state["i"] = i + 1
        return seq[i] if i < len(seq) else seq[-1]
    return health


def _recording_run_fn(calls):
    def run_fn(args, **kwargs):
        calls.append(list(args))
        return None
    return run_fn


def test_precheck_aborts_when_already_down(tmp_path):
    calls = []
    result = drill.run_drill(
        "http://x",
        health_fn=_health_seq([False]),
        run_fn=_recording_run_fn(calls),
        hook_fn=lambda _s: (DIRECTIVE_OK, 0),
        decisions_path=str(tmp_path / "d.jsonl"),
    )
    assert result.aborted is True
    assert result.passed is False
    assert ["omlx", "stop"] not in calls  # never forced an outage


def test_happy_path_passes(tmp_path):
    dpath = str(tmp_path / "d.jsonl")
    calls = []

    def hook_fn(_stdin):
        # Simulate the real hook writing exactly one counts-only infra_error line.
        logs.append_decision("infra_error", "unknown", 0.0, path=dpath)
        return DIRECTIVE_OK, 0

    result = drill.run_drill(
        "http://x",
        health_fn=_health_seq([True, False, True]),  # precheck, post-stop, recovered
        run_fn=_recording_run_fn(calls),
        hook_fn=hook_fn,
        decisions_path=dpath,
    )
    assert result.passed is True
    assert result.aborted is False
    assert "PAUSE" in result.captured_directive
    assert ["omlx", "stop"] in calls
    assert ["omlx", "start"] not in calls  # hook recovered it; no backstop needed


def test_recovery_backstop_runs_when_hook_fails_to_recover(tmp_path):
    dpath = str(tmp_path / "d.jsonl")
    calls = []

    def hook_fn(_stdin):
        logs.append_decision("infra_error", "unknown", 0.0, path=dpath)
        return DIRECTIVE_OK, 0

    result = drill.run_drill(
        "http://x",
        health_fn=_health_seq([True, False, False]),  # precheck, post-stop, NOT recovered
        run_fn=_recording_run_fn(calls),
        hook_fn=hook_fn,
        decisions_path=dpath,
    )
    assert result.passed is False
    assert result.aborted is False
    assert ["omlx", "start"] in calls  # drill's own backstop restarted it


def test_privacy_violation_fails(tmp_path):
    dpath = str(tmp_path / "d.jsonl")

    def hook_fn(_stdin):
        # A line carrying prompt text must fail the privacy assertion.
        with open(dpath, "a") as fh:
            fh.write(json.dumps({
                "ts": "t", "decision": "infra_error", "category": "x",
                "confidence": 0.0, "prompt": "secret user text",
            }) + "\n")
        return DIRECTIVE_OK, 0

    result = drill.run_drill(
        "http://x",
        health_fn=_health_seq([True, False, True]),
        run_fn=_recording_run_fn([]),
        hook_fn=hook_fn,
        decisions_path=dpath,
    )
    assert result.passed is False


def test_extract_context_handles_garbage():
    assert drill.extract_context("not json") == ""
    assert drill.extract_context(json.dumps({"hookSpecificOutput": {
        "additionalContext": "hello"}})) == "hello"
    assert drill.extract_context("") == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "/Users/brice/Claude Code work/mlx-mcp-server" && uv run pytest tests/test_hook_drill.py -v`
Expected: FAIL with `ModuleNotFoundError` / `AttributeError: module 'mlx_mcp_server.hook.drill' has no attribute 'run_drill'`.

- [ ] **Step 3: Write the implementation**

```python
# src/mlx_mcp_server/hook/drill.py
"""Case-2 live drill: force a real oMLX outage, drive the live mlx-offload-hook,
assert the full Case-2 path fired, and leave oMLX healthy (with a backstop).

Pure stdlib. Dependency-injected so the orchestration is unit-testable without a
live oMLX; main() wires the real defaults.
"""
import json
import os
from dataclasses import dataclass, field

from . import logs

# Fixed, clearly-offloadable, >40-char prompt: clears the prefilter so the hook
# reaches its first network call (classify), where the down-server transport
# error fires. The text need not be "good" — only non-trivial.
DRILL_PROMPT = (
    "Summarize the following release note in one short sentence: the offload "
    "hook retries a failed local generation once before escalating to Claude."
)
ALLOWED_DECISION_KEYS = {"ts", "decision", "category", "confidence"}


@dataclass
class DrillResult:
    passed: bool
    aborted: bool
    steps: list = field(default_factory=list)
    captured_directive: str = ""
    detail: str = ""


def extract_context(stdout):
    """Pull hookSpecificOutput.additionalContext from hook stdout; '' on failure."""
    try:
        obj = json.loads(stdout)
        return obj.get("hookSpecificOutput", {}).get("additionalContext", "") or ""
    except (ValueError, AttributeError, TypeError):
        return ""


def _count_lines(path):
    try:
        with open(path) as fh:
            return sum(1 for line in fh if line.strip())
    except OSError:
        return 0


def _last_obj(path):
    try:
        with open(path) as fh:
            lines = [ln for ln in fh.read().splitlines() if ln.strip()]
        return json.loads(lines[-1]) if lines else None
    except (OSError, ValueError, IndexError):
        return None


def run_drill(base_url, *, health_fn, run_fn, hook_fn, decisions_path,
              prompt=DRILL_PROMPT):
    """Force an outage, fire the hook, assert the Case-2 path, restore health.

    Never raises: all work is wrapped, and the finally block always attempts to
    bring oMLX back up if it is still down.
    """
    steps = []

    # 1. Pre-check — must be healthy, or we'd mask a real outage we didn't cause.
    if not health_fn(base_url):
        return DrillResult(
            passed=False, aborted=True,
            steps=[("precheck", False, "oMLX already down — aborting")],
            detail="aborted: oMLX was not healthy at start",
        )
    steps.append(("precheck", True, "oMLX healthy"))

    result = None
    try:
        before = _count_lines(decisions_path)

        # 3. Force the outage.
        run_fn(["omlx", "stop"], capture_output=True, text=True, timeout=30)
        down = not health_fn(base_url)
        steps.append(("stop", down,
                      "oMLX down" if down else "still responding after stop"))

        # 4. Drive the live hook with a crafted prompt.
        stdout, code = hook_fn(json.dumps({"prompt": prompt}))
        captured = extract_context(stdout)

        # 5. Assert the real Case-2 path fired.
        last = _last_obj(decisions_path)
        after = _count_lines(decisions_path)
        exit_ok = code == 0
        directive_ok = "PAUSE" in captured and "Do NOT silently proceed on Opus" in captured
        logged_ok = (after == before + 1 and bool(last)
                     and last.get("decision") == "infra_error")
        privacy_ok = bool(last) and set(last.keys()).issubset(ALLOWED_DECISION_KEYS)
        recovered = health_fn(base_url)

        steps += [
            ("hook_exit_0", exit_ok, f"exit={code}"),
            ("pause_directive", directive_ok, captured[:160]),
            ("infra_error_logged", logged_ok, f"+{after - before} line(s)"),
            ("privacy_counts_only", privacy_ok,
             str(sorted((last or {}).keys()))),
            ("recovered", recovered, "healthy" if recovered else "STILL DOWN"),
        ]
        passed = (down and exit_ok and directive_ok and logged_ok
                  and privacy_ok and recovered)
        result = DrillResult(passed=passed, aborted=False, steps=steps,
                             captured_directive=captured,
                             detail="PASS" if passed else "FAIL")
    except Exception as e:  # noqa: BLE001 - drill must never raise
        steps.append(("error", False, str(e)))
        result = DrillResult(passed=False, aborted=False, steps=steps,
                             detail=f"drill errored: {e}")
    finally:
        # Backstop: never leave a dead server.
        try:
            if not health_fn(base_url):
                run_fn(["omlx", "start"], capture_output=True, text=True, timeout=30)
        except Exception:  # noqa: BLE001
            pass
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "/Users/brice/Claude Code work/mlx-mcp-server" && uv run pytest tests/test_hook_drill.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
cd "/Users/brice/Claude Code work/mlx-mcp-server"
git add src/mlx_mcp_server/hook/drill.py tests/test_hook_drill.py
git commit -m "feat: Case-2 live drill orchestrator (run_drill)"
```

---

### Task 2: Entry point, console script, docs

**Files:**
- Modify: `src/mlx_mcp_server/hook/drill.py` (add `main`, `_exit_code`, `_print_report`, default deps)
- Modify: `pyproject.toml:18-20` (add console script), `pyproject.toml:7` (version 0.3.0 → 0.4.0)
- Modify: `README.md` (add "Case-2 live drill" subsection under the hook docs)
- Test: `tests/test_hook_drill.py` (add exit-code mapping tests)

**Interfaces:**
- Consumes: `DrillResult`, `run_drill` (Task 1); `omlx.resolve_omlx`, `restart._default_health`, `logs.DECISIONS_PATH` (existing).
- Produces: `_exit_code(result: DrillResult) -> int`; `main() -> int` (console entry); `mlx-case2-drill` script.

- [ ] **Step 1: Write the failing tests**

```python
# Append to tests/test_hook_drill.py
def test_exit_code_mapping():
    assert drill._exit_code(drill.DrillResult(passed=True, aborted=False)) == 0
    assert drill._exit_code(drill.DrillResult(passed=False, aborted=False)) == 1
    assert drill._exit_code(drill.DrillResult(passed=False, aborted=True)) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "/Users/brice/Claude Code work/mlx-mcp-server" && uv run pytest tests/test_hook_drill.py::test_exit_code_mapping -v`
Expected: FAIL with `AttributeError: ... has no attribute '_exit_code'`.

- [ ] **Step 3: Add the entry point**

Append to `src/mlx_mcp_server/hook/drill.py`:

```python
import subprocess  # add to the import block at the top of the file

from . import omlx
from .restart import _default_health


def _default_hook_fn(stdin_text):
    """Pipe the event JSON into the installed mlx-offload-hook; return (stdout, code)."""
    p = subprocess.run(["mlx-offload-hook"], input=stdin_text,
                       capture_output=True, text=True, timeout=120)
    return p.stdout, p.returncode


def _exit_code(result):
    if result.aborted:
        return 2
    return 0 if result.passed else 1


def _print_report(result):
    print("=== Case-2 live drill ===")
    for name, ok, detail in result.steps:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {detail}")
    if result.captured_directive:
        print("\n--- injected directive Claude would see ---")
        print(result.captured_directive)
    verdict = "ABORTED" if result.aborted else ("PASS" if result.passed else "FAIL")
    print(f"\n>>> {verdict}: {result.detail}")


def main():
    base_url, _api_key, _model = omlx.resolve_omlx()
    result = run_drill(
        base_url,
        health_fn=_default_health,
        run_fn=subprocess.run,
        hook_fn=_default_hook_fn,
        decisions_path=logs.DECISIONS_PATH,
    )
    _print_report(result)
    return _exit_code(result)


if __name__ == "__main__":
    import sys
    sys.exit(main())
```

(Move `import subprocess` and the `from . import omlx` / `from .restart import _default_health` lines up into the module's import block; shown here inline for clarity.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "/Users/brice/Claude Code work/mlx-mcp-server" && uv run pytest tests/test_hook_drill.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Register the console script and bump the version**

In `pyproject.toml`, under `[project.scripts]` (after line 20):

```toml
mlx-case2-drill = "mlx_mcp_server.hook.drill:main"
```

Change `pyproject.toml:7`:

```toml
version = "0.4.0"
```

- [ ] **Step 6: Document it in README.md**

Add this subsection under the offload-hook docs in `README.md`:

```markdown
### Case-2 live drill

`mlx-case2-drill` fires the hook's infrastructure-failure path (Case 2) for real,
once, on demand — proving the live recovery works end-to-end. Run it only when
oMLX is **idle and healthy**; it briefly stops the server.

It pre-checks health (aborts if already down so it never masks a real outage),
forces an outage with `omlx stop`, pipes a fixed offloadable prompt into the live
`mlx-offload-hook`, and asserts: the hook exits 0, injects the PAUSE directive,
logs exactly one counts-only `infra_error` decision, and that the hook's own
`omlx restart` brought the server back. If recovery failed, the drill runs
`omlx start` itself as a backstop and reports **FAIL**.

```bash
mlx-case2-drill   # exit 0 = PASS, 1 = FAIL, 2 = aborted (oMLX already down)
```
```

- [ ] **Step 7: Run the full suite and commit**

Run: `cd "/Users/brice/Claude Code work/mlx-mcp-server" && uv run pytest -q`
Expected: all tests pass (prior 171 + 6 new = 177).

```bash
cd "/Users/brice/Claude Code work/mlx-mcp-server"
git add src/mlx_mcp_server/hook/drill.py tests/test_hook_drill.py pyproject.toml README.md
git commit -m "feat: mlx-case2-drill console script + docs; v0.4.0"
```

---

## Post-implementation (controller, not a task)

- Reinstall the tool so the new console script lands on PATH: `uv tool install --reinstall .` (from the repo). The earlier hook work needed this because `uv run` alone doesn't expose new entry points to the live environment.
- Merge `case2-live-drill` → `main` directly (per the standing "Claude merges offload work" rule).
- **Decide with Brice before publishing 0.4.0 to PyPI** — the drill is an operational tool; PyPI publish is optional and is his call, not baked into this plan.
- The actual live run (`mlx-case2-drill` against the real server) is Brice's to trigger when oMLX is idle — that is the whole point of the drill and is not part of the build.
```
