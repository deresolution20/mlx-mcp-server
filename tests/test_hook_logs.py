import json
from mlx_mcp_server.hook import logs


def test_append_call_log_matches_server_schema(tmp_path):
    p = tmp_path / "call.jsonl"
    logs.append_call_log("M", "summarize", 10, 5, path=str(p), now_fn=lambda: "T")
    row = json.loads(p.read_text().strip())
    assert row == {"ts": "T", "model": "M", "category": "summarize",
                   "prompt_tokens": 10, "completion_tokens": 5,
                   "rounds": 1, "winning_rung": "local"}


def test_append_decision_writes_counts_only(tmp_path):
    p = tmp_path / "dec.jsonl"
    logs.append_decision("offloaded", "code", 0.8, path=str(p), now_fn=lambda: "T")
    row = json.loads(p.read_text().strip())
    assert row == {"ts": "T", "decision": "offloaded", "category": "code",
                   "confidence": 0.8}
    assert "text" not in row and "content" not in row and "prompt" not in row


def test_writers_never_raise_on_bad_path():
    # directory that cannot be created -> silently ignored
    logs.append_decision("offloaded", "code", 0.1, path="/proc/nonexistent/x.jsonl")
    logs.append_call_log("M", "code", 1, 1, path="/proc/nonexistent/x.jsonl")
