import json
import pytest
from dataclasses import dataclass

from mlx_mcp_server import server
from mlx_mcp_server.server import _param_size, _next_larger_model


# ── pure helpers ──────────────────────────────────────────────────────────────

def test_param_size_handles_moe_and_quant_tags():
    assert _param_size("Qwen3-Coder-30B-A3B-Instruct-MLX-4bit") == 30.0   # MoE: total, not active 3B
    assert _param_size("Qwen2.5-Coder-7B-Instruct-8bit") == 7.0           # 8bit quant ignored
    assert _param_size("Qwen2.5-Coder-14B-Instruct-4bit") == 14.0
    assert _param_size("DeepSeek-Coder-V2-Lite-Instruct-4bit-mlx") == 0.0  # no NNb in name


def test_next_larger_picks_smallest_above_current():
    av = ["Qwen2.5-Coder-7B-Instruct-4bit",
          "Qwen2.5-Coder-14B-Instruct-4bit",
          "Qwen3-Coder-30B-A3B-Instruct-MLX-4bit"]
    assert _next_larger_model("Qwen2.5-Coder-7B-Instruct-4bit", av) == "Qwen2.5-Coder-14B-Instruct-4bit"
    assert _next_larger_model("Qwen2.5-Coder-14B-Instruct-4bit", av) == "Qwen3-Coder-30B-A3B-Instruct-MLX-4bit"


def test_next_larger_empty_when_already_largest():
    av = ["Qwen2.5-Coder-7B-Instruct-4bit", "Qwen3-Coder-30B-A3B-Instruct-MLX-4bit"]
    assert _next_larger_model("Qwen3-Coder-30B-A3B-Instruct-MLX-4bit", av) == ""


# ── integration: the iterate tool auto-escalates to a bigger local model ───────

@dataclass
class _Resp:
    content: str
    prompt_tokens: int = 3
    completion_tokens: int = 2
    total_tokens: int = 5
    elapsed_seconds: float = 0.1
    model: str = "small-7B-4bit"


class _Client:
    def __init__(self, outputs, models, current):
        self._outputs = outputs
        self._i = 0
        self._models = models
        self._current = current
        self._runtime_model = current
        self.switched = []

    async def chat(self, **kwargs):
        out = self._outputs[min(self._i, len(self._outputs) - 1)]
        self._i += 1
        return _Resp(content=out)

    def set_model(self, m):
        self.switched.append(m)

    def get_active_model(self):
        return self._current

    async def _get_model(self):
        return self._current

    async def list_models(self):
        return [type("M", (), {"id": m})() for m in self._models]


@pytest.mark.asyncio
async def test_iterate_auto_escalates_to_bigger_model(tmp_path, monkeypatch):
    log = tmp_path / "mlx-call-log.jsonl"
    monkeypatch.setattr(server, "_CALL_LOG_PATH", str(log))
    # local model fails the gate 3x; the bigger model succeeds on the 4th attempt.
    fc = _Client(
        outputs=["bad", "bad", "bad", '{"ok": 1}'],
        models=["small-7B-4bit", "big-30B-4bit"],
        current="small-7B-4bit",
    )
    monkeypatch.setattr(server, "_client", fc)

    out = await server.iterate(message="make json", schema_keys=["ok"], max_local_rounds=3)

    rec = json.loads(log.read_text().strip().splitlines()[-1])
    assert rec["winning_rung"] == "local_big"
    assert rec["rounds"] == 4
    assert fc.switched[0] == "big-30B-4bit"   # auto-resolved + switched to the bigger model
    assert "rung 'local_big'" in out


@pytest.mark.asyncio
async def test_iterate_no_bigger_model_still_escalates(tmp_path, monkeypatch):
    log = tmp_path / "mlx-call-log.jsonl"
    monkeypatch.setattr(server, "_CALL_LOG_PATH", str(log))
    # current is already the largest -> no middle rung -> escalate to Claude.
    fc = _Client(
        outputs=["bad", "bad", "bad"],
        models=["small-7B-4bit", "big-30B-4bit"],
        current="big-30B-4bit",
    )
    monkeypatch.setattr(server, "_client", fc)

    out = await server.iterate(message="make json", schema_keys=["ok"], max_local_rounds=3)

    rec = json.loads(log.read_text().strip().splitlines()[-1])
    assert rec["winning_rung"] == "escalated"
    assert fc.switched == []          # never switched models
    assert "ESCALATE" in out.upper()
