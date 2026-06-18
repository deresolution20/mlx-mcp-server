from mlx_mcp_server.gates import GateResult, structural_gate


def test_structural_pass_when_no_checks():
    r = structural_gate("anything")
    assert r.passed is True and r.feedback == ""


def test_structural_min_len_fail():
    r = structural_gate("hi", min_len=10)
    assert r.passed is False
    assert "too short" in r.feedback


def test_structural_contains_fail():
    r = structural_gate("hello world", contains="goodbye")
    assert r.passed is False
    assert "goodbye" in r.feedback


def test_structural_contains_list_all_present():
    r = structural_gate("alpha beta gamma", contains=["alpha", "gamma"])
    assert r.passed is True and r.feedback == ""


def test_structural_contains_list_reports_only_missing():
    r = structural_gate("alpha beta", contains=["alpha", "zeta", "omega"])
    assert r.passed is False
    assert "zeta" in r.feedback and "omega" in r.feedback
    assert "alpha" not in r.feedback


def test_structural_regex_pass_and_fail():
    assert structural_gate("id=42", regex=r"id=\d+").passed is True
    bad = structural_gate("id=x", regex=r"id=\d+")
    assert bad.passed is False and "regex" in bad.feedback


def test_structural_invalid_json():
    r = structural_gate("not json", require_json=True)
    assert r.passed is False and "invalid JSON" in r.feedback


def test_structural_schema_keys_missing():
    r = structural_gate('{"a": 1}', schema_keys=["a", "b"])
    assert r.passed is False and "b" in r.feedback


def test_structural_schema_keys_pass():
    r = structural_gate('{"a": 1, "b": 2}', schema_keys=["a", "b"])
    assert r.passed is True


from mlx_mcp_server.gates import executable_gate


def test_executable_gate_pass():
    # command sees the candidate at $CANDIDATE_FILE; grep succeeds -> exit 0
    r = executable_gate("hello world", 'grep -q hello "$CANDIDATE_FILE"')
    assert r.passed is True and r.feedback == ""


def test_executable_gate_fail_captures_output():
    r = executable_gate("hello", 'echo "boom" >&2; exit 1')
    assert r.passed is False
    assert "boom" in r.feedback


def test_executable_gate_timeout():
    r = executable_gate("x", "sleep 5", timeout=1)
    assert r.passed is False and "timed out" in r.feedback
