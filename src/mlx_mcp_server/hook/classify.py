"""Stage 1: classify one prompt on the local model."""
import json
from dataclasses import dataclass

TASK_TYPES = ["summarize", "extract", "classify", "draft", "code", "reasoning", "other"]
OFFLOADABLE_TEXT = {"summarize", "extract", "classify", "draft"}

CLASSIFY_SYS = (
    "You label a single coding-assistant prompt. Return ONE JSON object: "
    '{"task_type":<one of ' + "/".join(TASK_TYPES) + '>,"offloadable":<true|false>,'
    '"confidence":<0..1>}. '
    "offloadable=true for summarize/extract/classify/draft and for SINGLE-FILE or "
    "single-function code (write a stub, add type hints, small refactor, explain "
    "an error). offloadable=false for multi-file or architectural work (label that "
    "task_type=reasoning) and for anything you are unsure about. "
    "confidence is how sure you are it is offloadable. Output ONLY the JSON object."
)


@dataclass
class Classification:
    task_type: str
    offloadable: bool
    confidence: float


def _coerce(obj):
    if not isinstance(obj, dict):
        return Classification("other", False, 0.0)
    tt = obj.get("task_type")
    if tt not in TASK_TYPES:
        tt = "other"
    off = bool(obj.get("offloadable"))
    try:
        conf = float(obj.get("confidence", 0.0))
    except (TypeError, ValueError):
        conf = 0.0
    conf = max(0.0, min(1.0, conf))
    return Classification(tt, off, conf)


def classify(prompt, chat_fn):
    """Classify a single prompt. chat_fn(system, user) -> ChatResult. Any parse
    failure falls back to a non-offloadable 'other'."""
    res = chat_fn(CLASSIFY_SYS, prompt[:4000])
    raw = res.content
    try:
        obj = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
    except (ValueError, KeyError):
        return Classification("other", False, 0.0)
    return _coerce(obj)
