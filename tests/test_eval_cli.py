import pytest
from mlx_mcp_server.eval import __main__ as cli
from mlx_mcp_server.eval.loader import EvalCase


@pytest.mark.asyncio
async def test_run_uses_provided_models_and_writes(tmp_path, monkeypatch):
    cases = [EvalCase(id="c1", category="boilerplate", prompt="p", system_prompt="",
                      suite_version=1, gate={"kind": "structural", "min_len": 1})]
    monkeypatch.setattr(cli, "load_suite", lambda d: cases)

    class _Resp:
        content = "ok"; prompt_tokens = 1; completion_tokens = 1; elapsed_seconds = 0.1

    class _Client:
        def __init__(self, *a, **k): pass
        async def chat(self, *, message, system_prompt): return _Resp()
        def set_model(self, m): pass
        async def list_models(self): return []
        def __getattr__(self, n): return ""  # _runtime_model etc.
        async def aclose(self): pass

    monkeypatch.setattr(cli, "LLMClient", _Client)
    monkeypatch.setattr(cli, "load_config", lambda: object())

    out = tmp_path / "results.jsonl"
    records = await cli._run(models=["m-a"], suite_dir="ignored",
                             out_path=str(out), eval_run_id="run1")
    assert len(records) == 1
    assert out.exists() and out.read_text().strip()


def test_default_suite_dir_points_at_bundled_suite():
    d = cli.default_suite_dir()
    assert d.endswith("suite")
