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
