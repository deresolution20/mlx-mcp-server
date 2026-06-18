"""Orchestrator: five stages, fully dependency-injected, never raises."""
from dataclasses import dataclass
from typing import Callable

from . import omlx, classify as classify_mod, generate as generate_mod
from . import logs, restart as restart_mod
from .prefilter import is_trivial as _is_trivial

CONFIDENCE_CUTOFF = 0.6
_EVENT_NAME = "UserPromptSubmit"


@dataclass
class Deps:
    """Injectable dependencies for the hook run."""
    resolve: Callable
    classify: Callable
    generate: Callable
    restart: Callable
    append_call_log: Callable
    append_decision: Callable
    is_trivial: Callable


def _default_deps():
    """Construct the real production Deps."""
    return Deps(
        resolve=omlx.resolve_omlx,
        classify=classify_mod.classify,
        generate=generate_mod.generate,
        restart=restart_mod.restart_omlx,
        append_call_log=logs.append_call_log,
        append_decision=logs.append_decision,
        is_trivial=_is_trivial,
    )


def _inject(text):
    """Wrap text as a UserPromptSubmit additionalContext JSON payload."""
    return {"hookSpecificOutput": {"hookEventName": _EVENT_NAME, "additionalContext": text}}


def _case2(deps, base_url, category):
    """Handle the oMLX-down Case-2 recovery path."""
    deps.append_decision("infra_error", category, 0.0)
    try:
        outcome = deps.restart(base_url)
    except Exception:  # noqa: BLE001 - recovery must not raise
        outcome = restart_mod.RestartOutcome(False, "restart attempt errored")
    state = "oMLX is healthy again" if outcome.healthy else "oMLX is STILL DOWN"
    return _inject(
        f"⚠️ oMLX errored on an offloadable prompt. Restart attempted — {state}.\n"
        f"{outcome.detail}\n\n"
        "Do NOT silently proceed on Opus for this. Tell Brice that oMLX errored, "
        "report this restart outcome, and PAUSE for his call (retry the offload, "
        "or wait while he looks)."
    )


def run(event, *, deps=None):
    """Return the stdout JSON dict to emit, or None to emit nothing. Never raises."""
    deps = deps or _default_deps()
    try:
        prompt = (event or {}).get("prompt") or ""
        if deps.is_trivial(prompt):
            return None
        base_url, api_key, model = deps.resolve()

        def chat(system, user):
            """Call the local model with a system and user prompt."""
            return omlx.chat(base_url, api_key, model, system, user)

        try:
            c = deps.classify(prompt, chat)
        except omlx.OmlxTransportError:
            return _case2(deps, base_url, "unknown")

        if not c.offloadable or c.confidence < CONFIDENCE_CUTOFF:
            deps.append_decision("passthrough", c.task_type, c.confidence)
            return None

        try:
            g = deps.generate(prompt, c.task_type, chat)
        except omlx.OmlxTransportError:
            return _case2(deps, base_url, c.task_type)

        if g.status != "ok":
            deps.append_decision("gate_escalate", c.task_type, c.confidence)
            return None

        deps.append_call_log(model, c.task_type, g.prompt_tokens, g.completion_tokens)
        deps.append_decision("offloaded", c.task_type, c.confidence)
        return _inject(
            f"LOCAL DRAFT (category={c.task_type}, model={model}):\n{g.text}\n\n"
            "Verify against the request; fix or escalate if inadequate, otherwise "
            "use it — do not regenerate from scratch."
        )
    except Exception:  # noqa: BLE001 - a hook must never break the prompt
        return None
