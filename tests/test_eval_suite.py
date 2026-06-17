import os
from mlx_mcp_server.eval.loader import load_suite, build_gate_fn

SUITE_DIR = os.path.join(
    os.path.dirname(__file__), "..", "src", "mlx_mcp_server", "eval", "suite"
)


def test_bundled_suite_loads_and_every_gate_builds():
    cases = load_suite(SUITE_DIR)
    # at least 3 cases in each of the six categories
    by_cat = {}
    for c in cases:
        by_cat.setdefault(c.category, 0)
        by_cat[c.category] += 1
    for cat in ("boilerplate", "summarize", "extract", "review", "explain", "codegen"):
        assert by_cat.get(cat, 0) >= 3, f"{cat} has too few cases"
    # every gate compiles to a callable
    for c in cases:
        assert callable(build_gate_fn(c.gate))
    # ids are unique
    ids = [c.id for c in cases]
    assert len(ids) == len(set(ids))
