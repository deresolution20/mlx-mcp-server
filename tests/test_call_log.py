import json
from mlx_mcp_server import server


def test_append_call_log_writes_jsonl(tmp_path, monkeypatch):
    log = tmp_path / "mlx-call-log.jsonl"
    monkeypatch.setattr(server, "_CALL_LOG_PATH", str(log))
    server._append_call_log(model="m1", category="review", prompt_tokens=10, completion_tokens=4)
    server._append_call_log(model="m1", category="other", prompt_tokens=1, completion_tokens=2)
    lines = log.read_text().strip().splitlines()
    assert len(lines) == 2
    rec = json.loads(lines[0])
    assert rec["model"] == "m1" and rec["category"] == "review"
    assert rec["prompt_tokens"] == 10 and rec["completion_tokens"] == 4
    assert "ts" in rec
    # never logs content
    assert "message" not in rec and "content" not in rec


def test_append_call_log_swallows_errors(monkeypatch):
    monkeypatch.setattr(server, "_CALL_LOG_PATH", "/nonexistent-dir/xyz/log.jsonl")
    # must not raise — logging is best-effort
    server._append_call_log(model="m", category="c", prompt_tokens=1, completion_tokens=1)


def test_append_call_log_records_rounds_and_rung(tmp_path, monkeypatch):
    log = tmp_path / "mlx-call-log.jsonl"
    monkeypatch.setattr(server, "_CALL_LOG_PATH", str(log))
    server._append_call_log(
        model="m1", category="boilerplate", prompt_tokens=20, completion_tokens=9,
        rounds=3, winning_rung="local_big",
    )
    rec = json.loads(log.read_text().strip().splitlines()[0])
    assert rec["rounds"] == 3
    assert rec["winning_rung"] == "local_big"


def test_append_call_log_rounds_default(tmp_path, monkeypatch):
    log = tmp_path / "mlx-call-log.jsonl"
    monkeypatch.setattr(server, "_CALL_LOG_PATH", str(log))
    server._append_call_log(model="m", category="other", prompt_tokens=1, completion_tokens=1)
    rec = json.loads(log.read_text().strip().splitlines()[0])
    assert rec["rounds"] == 1
    assert rec["winning_rung"] == "local"
