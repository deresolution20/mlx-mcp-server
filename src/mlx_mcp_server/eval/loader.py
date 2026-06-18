"""Loads eval cases and builds gate functions from the curated suite."""
import glob
import os
from dataclasses import dataclass

import yaml

from ..gates import structural_gate, executable_gate

_STRUCTURAL_KEYS = ("require_json", "schema_keys", "contains", "regex", "min_len")


@dataclass
class EvalCase:
    """One eval case with its prompt and gate spec."""
    id: str
    category: str
    prompt: str
    system_prompt: str
    suite_version: int
    gate: dict


def build_gate_fn(gate):
    """Turn a case's `gate` dict into a (text) -> GateResult callable over gates.py."""
    kind = gate.get("kind")
    if kind == "structural":
        params = {k: gate[k] for k in _STRUCTURAL_KEYS if k in gate}
        return lambda text: structural_gate(text, **params)
    if kind == "executable":
        cmd = gate["check_command"]
        timeout = gate.get("timeout", 60)
        return lambda text: executable_gate(text, cmd, timeout=timeout)
    raise ValueError(f"unknown gate kind: {kind!r}")


def load_suite(suite_dir):
    """Read every *.yaml in suite_dir into a flat list of EvalCase."""
    cases = []
    for path in sorted(glob.glob(os.path.join(suite_dir, "*.yaml"))):
        with open(path) as fh:
            data = yaml.safe_load(fh)
        suite_version = data["suite_version"]
        category = data["category"]
        for c in data["cases"]:
            cases.append(EvalCase(
                id=c["id"],
                category=category,
                prompt=c["prompt"],
                system_prompt=c.get("system_prompt", ""),
                suite_version=suite_version,
                gate=c["gate"],
            ))
    return cases
