import textwrap
import pytest

from mlx_mcp_server.eval.loader import EvalCase, build_gate_fn, load_suite


def test_build_gate_fn_structural_passes_and_fails():
    gate = {"kind": "structural", "contains": "def ", "min_len": 3}
    gate_fn = build_gate_fn(gate)
    assert gate_fn("def foo(): pass").passed is True
    assert gate_fn("nope").passed is False


def test_build_gate_fn_executable_runs_command():
    gate = {"kind": "executable", "check_command": "grep -q hello $CANDIDATE_FILE"}
    gate_fn = build_gate_fn(gate)
    assert gate_fn("hello world").passed is True
    assert gate_fn("goodbye").passed is False


def test_build_gate_fn_unknown_kind_raises():
    with pytest.raises(ValueError):
        build_gate_fn({"kind": "telepathy"})


def test_load_suite_reads_all_cases(tmp_path):
    (tmp_path / "boilerplate.yaml").write_text(textwrap.dedent("""
        suite_version: 1
        category: boilerplate
        cases:
          - id: bp-one
            prompt: "write x"
            system_prompt: "be terse"
            gate:
              kind: structural
              min_len: 1
          - id: bp-two
            prompt: "write y"
            gate:
              kind: structural
              contains: "y"
    """))
    cases = load_suite(str(tmp_path))
    assert [c.id for c in cases] == ["bp-one", "bp-two"]
    assert cases[0].category == "boilerplate"
    assert cases[0].suite_version == 1
    assert cases[0].system_prompt == "be terse"
    assert cases[1].system_prompt == ""  # defaults to empty
