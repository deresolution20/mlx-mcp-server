"""Runs eval cases grouped by model, resilient to backend errors."""
import time
from dataclasses import dataclass

from .loader import build_gate_fn


@dataclass
class EvalRecord:
    """One counts-only eval result record."""
    eval_run_id: str
    ts: float
    model: str
    category: str
    case_id: str
    suite_version: int
    passed: bool
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int
    rounds: int
    error: str = ""


async def run_eval(*, chat_fn, set_model_fn, get_model_fn, models, cases,
                   eval_run_id, now_fn=time.time):
    """Run every model against every case. Groups by model (one set_model per
    model) to respect the warm pool. A backend error becomes a failed record,
    never a crash. Restores the originally-active model at the end.

    PRIVACY: only counts/labels are recorded. `error` holds backend-exception
    strings only (never gate feedback, which can echo candidate code).
    """
    original = get_model_fn()
    records = []
    try:
        for model in models:
            set_model_fn(model)
            for case in cases:
                gate_fn = build_gate_fn(case.gate)
                try:
                    resp = await chat_fn(message=case.prompt,
                                         system_prompt=case.system_prompt)
                except Exception as e:  # backend down / OOM / timeout
                    records.append(EvalRecord(
                        eval_run_id=eval_run_id, ts=now_fn(), model=model,
                        category=case.category, case_id=case.id,
                        suite_version=case.suite_version, passed=False,
                        prompt_tokens=0, completion_tokens=0, latency_ms=0,
                        rounds=1, error=f"backend error: {e}"[:500],
                    ))
                    continue
                gr = gate_fn(resp.content)
                records.append(EvalRecord(
                    eval_run_id=eval_run_id, ts=now_fn(), model=model,
                    category=case.category, case_id=case.id,
                    suite_version=case.suite_version, passed=gr.passed,
                    prompt_tokens=resp.prompt_tokens,
                    completion_tokens=resp.completion_tokens,
                    latency_ms=int(resp.elapsed_seconds * 1000),
                    rounds=1, error="",  # gate feedback intentionally NOT stored
                ))
    finally:
        set_model_fn(original)
    return records
