import json

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


def test_exit_code_mapping():
    assert drill._exit_code(drill.DrillResult(passed=True, aborted=False)) == 0
    assert drill._exit_code(drill.DrillResult(passed=False, aborted=False)) == 1
    assert drill._exit_code(drill.DrillResult(passed=False, aborted=True)) == 2
