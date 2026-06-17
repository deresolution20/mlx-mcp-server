import json
import pytest
from dataclasses import dataclass

from mlx_mcp_server import server


@dataclass
class FakeResp:
    content: str
    prompt_tokens: int = 7
    completion_tokens: int = 4
    total_tokens: int = 11
    elapsed_seconds: float = 0.1
    model: str = "fake-model"


class FakeClient:
    def __init__(self, outputs):
        self._outputs = outputs
        self._i = 0
        self._runtime_model = "fake-model"
        self.switched = []

    async def chat(self, **kwargs):
        out = self._outputs[min(self._i, len(self._outputs) - 1)]
        self._i += 1
        return FakeResp(content=out)

    def set_model(self, m):
        self.switched.append(m)

    def get_active_model(self):
        return self._runtime_model


@pytest.mark.asyncio
async def test_iterate_tool_logs_rounds_and_rung(tmp_path, monkeypatch):
    log = tmp_path / "mlx-call-log.jsonl"
    monkeypatch.setattr(server, "_CALL_LOG_PATH", str(log))
    monkeypatch.setattr(server, "_client", FakeClient(['{"ok": 1}']))

    out = await server.iterate(message="make json", category="boilerplate", schema_keys=["ok"])

    assert "LOCAL" in out
    rec = json.loads(log.read_text().strip().splitlines()[0])
    assert rec["category"] == "boilerplate"
    assert rec["rounds"] == 1
    assert rec["winning_rung"] == "local"


@pytest.mark.asyncio
async def test_iterate_tool_escalation_surfaces_flag(tmp_path, monkeypatch):
    log = tmp_path / "mlx-call-log.jsonl"
    monkeypatch.setattr(server, "_CALL_LOG_PATH", str(log))
    monkeypatch.setattr(server, "_client", FakeClient(["bad", "bad", "bad"]))

    out = await server.iterate(message="make json", schema_keys=["ok"], max_local_rounds=3)

    assert "ESCALATE" in out.upper()
    rec = json.loads(log.read_text().strip().splitlines()[0])
    assert rec["winning_rung"] == "escalated"


@pytest.mark.asyncio
async def test_iterate_tool_no_gate_marks_verify(tmp_path, monkeypatch):
    log = tmp_path / "mlx-call-log.jsonl"
    monkeypatch.setattr(server, "_CALL_LOG_PATH", str(log))
    monkeypatch.setattr(server, "_client", FakeClient(["a prose summary"]))

    out = await server.iterate(message="summarize", category="summarize")

    assert "VERIFY" in out.upper()
    rec = json.loads(log.read_text().strip().splitlines()[0])
    assert rec["rounds"] == 1
