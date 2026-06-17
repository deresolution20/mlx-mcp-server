import pytest
from dataclasses import dataclass

from mlx_mcp_server.iterate import run_iterate, IterateResult
from mlx_mcp_server.gates import structural_gate


@dataclass
class FakeResp:
    content: str
    prompt_tokens: int = 5
    completion_tokens: int = 3
    model: str = "small-model"


def make_chat_fn(scripted):
    """scripted: list of strings to return in order; records messages seen."""
    calls = {"messages": [], "i": 0}

    async def chat_fn(message, system_prompt=""):
        calls["messages"].append(message)
        out = scripted[min(calls["i"], len(scripted) - 1)]
        calls["i"] += 1
        return FakeResp(content=out)

    return chat_fn, calls


@pytest.mark.asyncio
async def test_pass_on_first_round():
    chat_fn, calls = make_chat_fn(['{"ok": 1}'])
    r = await run_iterate(
        chat_fn=chat_fn, message="make json",
        gate_fn=lambda t: structural_gate(t, schema_keys=["ok"]),
    )
    assert r.passed is True
    assert r.escalate is False
    assert r.rounds == 1
    assert r.winning_rung == "local"
    assert calls["i"] == 1


@pytest.mark.asyncio
async def test_retry_feeds_failure_then_passes():
    chat_fn, calls = make_chat_fn(["nope", '{"ok": 1}'])
    r = await run_iterate(
        chat_fn=chat_fn, message="make json",
        gate_fn=lambda t: structural_gate(t, schema_keys=["ok"]),
    )
    assert r.passed is True and r.rounds == 2 and r.winning_rung == "local"
    # the second prompt must contain the first failure's feedback
    assert "invalid JSON" in calls["messages"][1] or "missing keys" in calls["messages"][1]


@pytest.mark.asyncio
async def test_exhaust_local_then_escalate_without_big_model():
    chat_fn, calls = make_chat_fn(["bad", "bad", "bad"])
    r = await run_iterate(
        chat_fn=chat_fn, message="make json", max_local_rounds=3,
        gate_fn=lambda t: structural_gate(t, schema_keys=["ok"]),
    )
    assert r.escalate is True
    assert r.passed is False
    assert r.winning_rung == "escalated"
    assert r.rounds == 3
    assert len(r.history) == 3


@pytest.mark.asyncio
async def test_big_model_rung_succeeds():
    chat_fn, calls = make_chat_fn(["bad", "bad", '{"ok": 1}'])
    switched = []
    r = await run_iterate(
        chat_fn=chat_fn, message="make json", max_local_rounds=2,
        gate_fn=lambda t: structural_gate(t, schema_keys=["ok"]),
        big_model="big-model",
        set_model_fn=lambda m: switched.append(m),
        get_model_fn=lambda: "small-model",
    )
    assert r.passed is True
    assert r.winning_rung == "local_big"
    assert r.rounds == 3
    # switched to big model, then restored to the original
    assert switched == ["big-model", "small-model"]


@pytest.mark.asyncio
async def test_no_gate_single_shot_needs_verify():
    chat_fn, calls = make_chat_fn(["some prose answer"])
    r = await run_iterate(chat_fn=chat_fn, message="summarize this", gate_fn=None)
    assert r.passed is None
    assert r.escalate is False
    assert r.rounds == 1
    assert r.winning_rung == "local"
    assert calls["i"] == 1


@pytest.mark.asyncio
async def test_token_totals_accumulate_across_rounds():
    chat_fn, calls = make_chat_fn(["bad", "bad", "bad"])
    r = await run_iterate(
        chat_fn=chat_fn, message="x", max_local_rounds=3,
        gate_fn=lambda t: structural_gate(t, min_len=100),
    )
    assert r.prompt_tokens == 15  # 3 rounds × 5
    assert r.completion_tokens == 9  # 3 rounds × 3
