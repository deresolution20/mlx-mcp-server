from mlx_mcp_server.hook import run as runmod
from mlx_mcp_server.hook.run import run, Deps
from mlx_mcp_server.hook.classify import Classification
from mlx_mcp_server.hook.generate import GenResult
from mlx_mcp_server.hook.restart import RestartOutcome
from mlx_mcp_server.hook.omlx import OmlxTransportError


def _deps(**over):
    rec = {"decisions": [], "calls": []}
    base = dict(
        resolve=lambda: ("http://x", "k", "M"),
        classify=lambda prompt, chat: Classification("summarize", True, 0.9),
        generate=lambda prompt, cat, chat: GenResult("ok", "LOCAL ANSWER", 10, 5),
        restart=lambda base_url: RestartOutcome(True, "healthy"),
        append_call_log=lambda *a, **k: rec["calls"].append((a, k)),
        append_decision=lambda decision, cat, conf, **k: rec["decisions"].append(decision),
        is_trivial=lambda p: False,
    )
    base.update(over)
    return Deps(**base), rec


def test_trivial_prompt_emits_nothing():
    deps, rec = _deps(is_trivial=lambda p: True)
    assert run({"prompt": "ok"}, deps=deps) is None
    assert rec["decisions"] == []


def test_offloadable_injects_local_draft_and_logs():
    deps, rec = _deps()
    out = run({"prompt": "summarize this long thing here please"}, deps=deps)
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert "LOCAL DRAFT" in ctx and "LOCAL ANSWER" in ctx
    assert rec["decisions"] == ["offloaded"]
    assert len(rec["calls"]) == 1


def test_low_confidence_passes_through():
    deps, rec = _deps(classify=lambda p, c: Classification("summarize", True, 0.3))
    assert run({"prompt": "x" * 80}, deps=deps) is None
    assert rec["decisions"] == ["passthrough"]


def test_gate_escalate_passes_through_silently():
    deps, rec = _deps(generate=lambda p, cat, c: GenResult("escalate", "", 1, 1))
    assert run({"prompt": "x" * 80}, deps=deps) is None
    assert rec["decisions"] == ["gate_escalate"]


def test_transport_error_triggers_loud_pause_directive():
    def boom(prompt, chat):
        raise OmlxTransportError("connection refused")
    deps, rec = _deps(classify=boom)
    out = run({"prompt": "x" * 80}, deps=deps)
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert "PAUSE" in ctx and "oMLX" in ctx
    assert rec["decisions"] == ["infra_error"]


def test_run_never_raises_on_unexpected_error():
    def boom(prompt, chat):
        raise RuntimeError("unexpected")
    deps, rec = _deps(classify=boom)
    # A non-transport error is swallowed by the outer guard -> emit nothing.
    assert run({"prompt": "x" * 80}, deps=deps) is None
