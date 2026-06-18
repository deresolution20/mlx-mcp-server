"""Structural and executable gates used by the iterate offload loop."""
import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass


@dataclass
class GateResult:
    """Whether a gate passed, plus feedback text for a retry."""
    passed: bool
    feedback: str  # error text to feed back into a retry; "" when passed


def structural_gate(
    text,
    *,
    require_json=False,
    schema_keys=None,
    contains=None,
    regex=None,
    min_len=0,
) -> GateResult:
    """Cheap, content-free checks. Returns on the FIRST failed check."""
    stripped = text.strip()

    if min_len and len(stripped) < min_len:
        return GateResult(False, f"output too short: {len(stripped)} < {min_len} chars")

    if contains is not None:
        needles = [contains] if isinstance(contains, str) else list(contains)
        missing = [n for n in needles if n not in text]
        if missing:
            label = missing[0] if len(missing) == 1 else missing
            return GateResult(False, f"missing required substring: {label!r}")

    if regex and not re.search(regex, text):
        return GateResult(False, f"output did not match regex: {regex}")

    if require_json or schema_keys:
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError as e:
            return GateResult(False, f"invalid JSON: {e}")
        if schema_keys:
            if not isinstance(parsed, dict):
                return GateResult(False, "JSON is not an object/dict")
            missing = [k for k in schema_keys if k not in parsed]
            if missing:
                return GateResult(False, f"JSON missing keys: {missing}")

    return GateResult(True, "")


def executable_gate(text, check_command, *, timeout=60) -> GateResult:
    """Write the candidate to a temp file exposed as $CANDIDATE_FILE, then run
    check_command in a shell. Exit 0 = pass; non-zero = fail with captured output.
    """
    temp_file = None
    try:
        temp_file = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)
        temp_file.write(text)
        temp_file.close()

        env = dict(os.environ)
        env["CANDIDATE_FILE"] = temp_file.name

        result = subprocess.run(
            check_command,
            shell=True,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0:
            return GateResult(True, "")
        combined = (result.stdout + result.stderr).strip()[:2000]
        return GateResult(False, combined or f"gate command exited {result.returncode}")
    except subprocess.TimeoutExpired:
        return GateResult(False, f"gate command timed out after {timeout}s")
    finally:
        if temp_file is not None and os.path.exists(temp_file.name):
            os.unlink(temp_file.name)
