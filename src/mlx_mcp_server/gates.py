import json
import re
from dataclasses import dataclass


@dataclass
class GateResult:
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

    if contains is not None and contains not in text:
        return GateResult(False, f"missing required substring: {contains!r}")

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
