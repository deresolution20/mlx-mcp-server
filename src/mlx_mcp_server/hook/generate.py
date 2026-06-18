"""Stage 2: generate the answer locally and gate it; retry once, else escalate."""
import re
import sys
from dataclasses import dataclass

from mlx_mcp_server.gates import structural_gate, executable_gate, GateResult

_MIN_LEN = 20
_PY_BLOCK = re.compile(r"```python\s*\n(.*?)```", re.DOTALL)

GEN_SYS = (
    "You are a fast, concise coding assistant. Answer the user's request directly "
    "and completely. Do not add preamble or ask clarifying questions."
)


@dataclass
class GenResult:
    """A gated local-generation result."""
    status: str  # "ok" | "escalate"
    text: str
    prompt_tokens: int
    completion_tokens: int


def gate_for(category, candidate):
    """Build a gate function for a given category and candidate."""
    base = structural_gate(candidate, min_len=_MIN_LEN)
    if not base.passed:
        return base
    if category == "code":
        for block in _PY_BLOCK.findall(candidate):
            r = executable_gate(
                block,
                f'"{sys.executable}" -c "import py_compile,sys; py_compile.compile(sys.argv[1], doraise=True)" "$CANDIDATE_FILE"',
                timeout=30,
            )
            if not r.passed:
                return r
    return GateResult(True, "")


def generate(prompt, category, chat_fn):
    """Generate, gate, retry once with feedback, else escalate."""
    user = prompt[:6000]
    last = None
    for attempt in range(2):
        res = chat_fn(GEN_SYS, user)
        last = res
        gate = gate_for(category, res.content)
        if gate.passed:
            return GenResult("ok", res.content, res.prompt_tokens, res.completion_tokens)
        user = f"{prompt[:6000]}\n\n(Your previous answer was rejected: {gate.feedback}. Fix it.)"
    return GenResult("escalate", "",
                     last.prompt_tokens if last else 0,
                     last.completion_tokens if last else 0)
