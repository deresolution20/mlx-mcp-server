import json
from mlx_mcp_server.eval.runner import EvalRecord
from mlx_mcp_server.eval.results import write_results, summarize, ALLOWED_KEYS


def _rec(model, cat, cid, passed, lat, ctok):
    return EvalRecord(
        eval_run_id="r", ts=1.0, model=model, category=cat, case_id=cid,
        suite_version=1, passed=passed, prompt_tokens=3,
        completion_tokens=ctok, latency_ms=lat, rounds=1, error="",
    )


def test_write_results_jsonl_only_allowed_keys(tmp_path):
    path = tmp_path / "results.jsonl"
    write_results([_rec("m", "boilerplate", "c1", True, 100, 10)], str(path))
    line = path.read_text().strip()
    row = json.loads(line)
    assert set(row) <= ALLOWED_KEYS
    # privacy: no prompt/completion text keys ever
    assert "prompt" not in row and "content" not in row and "completion" not in row


def test_summarize_computes_pass_rate_and_medians():
    recs = [
        _rec("m", "boilerplate", "c1", True, 100, 10),
        _rec("m", "boilerplate", "c2", False, 300, 20),
        _rec("m", "boilerplate", "c3", True, 200, 30),
    ]
    s = summarize(recs)
    cell = s[("m", "boilerplate")]
    assert cell["n"] == 3
    assert abs(cell["pass_rate"] - (2 / 3)) < 1e-9
    assert cell["median_latency_ms"] == 200
    assert cell["mean_completion_tokens"] == 20
