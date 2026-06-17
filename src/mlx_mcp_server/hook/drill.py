"""Case-2 live drill: force a real oMLX outage, drive the live mlx-offload-hook,
assert the full Case-2 path fired, and leave oMLX healthy (with a backstop).

Pure stdlib. Dependency-injected so the orchestration is unit-testable without a
live oMLX; main() wires the real defaults.
"""
import json
import subprocess
from dataclasses import dataclass, field

from . import logs, omlx
from .restart import _default_health

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
