from mlx_mcp_server.hook.generate import generate, gate_for, GenResult
from mlx_mcp_server.hook.omlx import ChatResult


def _seq_chat(*replies):
    calls = {"i": 0}
    def chat(system, user):
        r = replies[min(calls["i"], len(replies) - 1)]
        calls["i"] += 1
        return ChatResult(r, 7, 9)
    return chat


def test_gate_for_text_passes_long_enough():
    assert gate_for("summarize", "This is a sufficiently long summary line.").passed


def test_gate_for_text_fails_too_short():
    assert gate_for("summarize", "ok").passed is False


def test_gate_for_code_fails_uncompilable_python_block():
    bad = "Here:\n```python\ndef f( : pass\n```"
    assert gate_for("code", bad).passed is False


def test_gate_for_code_passes_compilable_python_block():
    good = "Here is a stub:\n```python\ndef f():\n    pass\n```"
    assert gate_for("code", good).passed is True


def test_generate_ok_on_first_pass():
    g = generate("summarize x", "summarize", _seq_chat("A nice long enough summary of x."))
    assert g.status == "ok"
    assert "summary" in g.text


def test_generate_escalates_after_two_gate_failures():
    g = generate("summarize x", "summarize", _seq_chat("no", "still"))
    assert g.status == "escalate"
