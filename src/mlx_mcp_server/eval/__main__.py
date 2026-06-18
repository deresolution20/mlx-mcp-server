"""CLI entry point for running the gated benchmark suite across local models."""
import argparse
import asyncio
import os
import uuid

from ..config import load_config
from ..client import LLMClient
from .loader import load_suite
from .runner import run_eval
from .results import write_results, summarize


def default_suite_dir():
    """Path to the bundled eval suite directory."""
    return os.path.join(os.path.dirname(__file__), "suite")


def _default_out():
    """Default results output path."""
    return os.path.join(os.path.expanduser("~"), ".omlx", "eval-results.jsonl")


async def _run(*, models, suite_dir, out_path, eval_run_id):
    """Run the eval suite across models and write results."""
    cases = load_suite(suite_dir)
    config = load_config()
    client = LLMClient(config)
    try:
        if not models:
            models = [m.id for m in await client.list_models()]
        records = await run_eval(
            chat_fn=client.chat,
            set_model_fn=client.set_model,
            get_model_fn=lambda: client._runtime_model,
            models=models,
            cases=cases,
            eval_run_id=eval_run_id,
        )
    finally:
        await client.aclose()
    out_dir = os.path.dirname(out_path)
    if out_dir:  # bare filename (e.g. --out results.jsonl) has no dir component
        os.makedirs(out_dir, exist_ok=True)
    write_results(records, out_path)
    return records


def _print_summary(records):
    """Print an aggregated results summary."""
    summary = summarize(records)
    print(f"\n{'model':<48} {'category':<12} {'pass':>6} {'p50 ms':>8} {'tok':>6}  n")
    for (model, cat), c in sorted(summary.items()):
        print(f"{model:<48} {cat:<12} {c['pass_rate']*100:5.0f}% "
              f"{c['median_latency_ms']:8.0f} {c['mean_completion_tokens']:6.0f}  {c['n']}")


def main(argv=None):
    """Eval CLI entry point."""
    parser = argparse.ArgumentParser(prog="python -m mlx_mcp_server.eval")
    sub = parser.add_subparsers(dest="cmd", required=True)
    run_p = sub.add_parser("run", help="run the eval suite against installed models")
    run_p.add_argument("--models", nargs="*", default=None,
                       help="model ids to eval (default: all installed)")
    run_p.add_argument("--suite", default=default_suite_dir())
    run_p.add_argument("--out", default=_default_out())
    args = parser.parse_args(argv)

    if args.cmd == "run":
        eval_run_id = uuid.uuid4().hex[:8]
        records = asyncio.run(_run(models=args.models, suite_dir=args.suite,
                                   out_path=args.out, eval_run_id=eval_run_id))
        _print_summary(records)
        print(f"\nwrote {len(records)} records to {args.out} (run {eval_run_id})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
