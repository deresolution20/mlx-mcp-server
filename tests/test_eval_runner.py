import pytest
from dataclasses import dataclass

from mlx_mcp_server.eval.loader import EvalCase
from mlx_mcp_server.eval.runner import run_eval, EvalRecord


@dataclass
class _Resp:
    content: str
    prompt_tokens: int = 5
    completion_tokens: int = 7
    elapsed_seconds: float = 0.25
    model: str = ""


class _FakeClient:
    """Returns a canned response per (model, case_id); records set_model calls."""
    def __init__(self, answers, current="m-small", boom=None):
        self._answers = answers      # {(model, case_id): content}
        self._current = current
        self.switched = []
        self._boom = boom or set()   # {(model, case_id)} that raise

    async def chat(self, *, message, system_prompt):
        # find the case by message; tests use distinct prompts
        raise AssertionError("use chat_for")

    def set_model(self, m):
        self.switched.append(m)
        self._current = m

    def get_model(self):
        return self._current


def _cases():
    return [
        EvalCase(id="c-ok", category="boilerplate", prompt="p1", system_prompt="",
                 suite_version=1, gate={"kind": "structural", "contains": "good"}),
        EvalCase(id="c-bad", category="boilerplate", prompt="p2", system_prompt="",
                 suite_version=1, gate={"kind": "structural", "contains": "good"}),
    ]


@pytest.mark.asyncio
async def test_run_eval_records_pass_fail_and_groups_by_model():
    cases = _cases()

    async def chat_fn(*, message, system_prompt):
        # c-ok -> "good", c-bad -> "nope"
        return _Resp(content="good" if message == "p1" else "nope")

    switched = []
    records = await run_eval(
        chat_fn=chat_fn,
        set_model_fn=lambda m: switched.append(m),
        get_model_fn=lambda: "orig",
        models=["m-a", "m-b"],
        cases=cases,
        eval_run_id="run1",
        now_fn=lambda: 123.0,
    )
    # 2 models x 2 cases = 4 records
    assert len(records) == 4
    # grouped by model: switched once per model, then restored to orig
    assert switched == ["m-a", "m-b", "orig"]
    ok = [r for r in records if r.case_id == "c-ok"]
    bad = [r for r in records if r.case_id == "c-bad"]
    assert all(r.passed for r in ok)
    assert all(not r.passed for r in bad)
    # token + latency captured; gate feedback NEVER stored as error
    assert ok[0].prompt_tokens == 5 and ok[0].completion_tokens == 7
    assert ok[0].latency_ms == 250
    assert all(r.error == "" for r in records)  # no backend errors here


@pytest.mark.asyncio
async def test_run_eval_backend_error_becomes_failed_record_not_crash():
    cases = _cases()[:1]

    async def chat_fn(*, message, system_prompt):
        raise RuntimeError("507 out of memory")

    records = await run_eval(
        chat_fn=chat_fn,
        set_model_fn=lambda m: None,
        get_model_fn=lambda: "orig",
        models=["m-a"],
        cases=cases,
        eval_run_id="run1",
        now_fn=lambda: 1.0,
    )
    assert len(records) == 1
    assert records[0].passed is False
    assert "507 out of memory" in records[0].error
    assert records[0].latency_ms == 0
