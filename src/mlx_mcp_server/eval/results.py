import json
import statistics
from dataclasses import asdict

ALLOWED_KEYS = {
    "eval_run_id", "ts", "model", "category", "case_id", "suite_version",
    "passed", "prompt_tokens", "completion_tokens", "latency_ms", "rounds",
    "error",
}


def write_results(records, path):
    """Append each record as one JSON line. Enforces the privacy invariant:
    only label/count keys, never prompt or completion text."""
    with open(path, "a") as fh:
        for r in records:
            row = asdict(r)
            extra = set(row) - ALLOWED_KEYS
            assert not extra, f"disallowed result keys: {extra}"
            fh.write(json.dumps(row) + "\n")


def summarize(records):
    """Aggregate by (model, category)."""
    groups = {}
    for r in records:
        groups.setdefault((r.model, r.category), []).append(r)
    out = {}
    for key, recs in groups.items():
        passed = sum(1 for r in recs if r.passed)
        out[key] = {
            "n": len(recs),
            "pass_rate": passed / len(recs),
            "median_latency_ms": statistics.median(r.latency_ms for r in recs),
            "mean_completion_tokens": statistics.mean(r.completion_tokens for r in recs),
        }
    return out
