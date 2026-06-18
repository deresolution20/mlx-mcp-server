"""Local-first escalation ladder: retry locally, try a bigger local model, then escalate to Claude."""
from dataclasses import dataclass, field


@dataclass
class IterateResult:
    """Outcome of an iterate run: content, passed, escalate, rounds, winning rung."""
    content: str
    passed: bool | None  # None = no gate ran; Claude should verify
    escalate: bool
    rounds: int
    winning_rung: str  # "local" | "local_big" | "escalated"
    model: str
    prompt_tokens: int
    completion_tokens: int
    history: list = field(default_factory=list)  # gate feedback per failed round


def _retry_message(original, feedback):
    """Compose a retry prompt embedding the gate's failure feedback."""
    return (
        f"{original}\n\n"
        f"Your previous attempt failed this check:\n{feedback}\n\n"
        f"Fix it and return only the corrected output."
    )


async def run_iterate(
    *,
    chat_fn,
    message,
    system_prompt="",
    gate_fn=None,
    max_local_rounds=3,
    big_model="",
    set_model_fn=None,
    get_model_fn=None,
):
    """Run the local-first escalation ladder. `chat_fn` is an async callable
    (message, system_prompt) -> object with .content/.model/.prompt_tokens/
    .completion_tokens. `gate_fn` is (text) -> GateResult, or None for no gate.
    """
    totals = {"p": 0, "c": 0}
    history = []
    last_content = ""
    last_model = ""

    async def attempt(msg):
        """Run one local model attempt for the given message."""
        nonlocal last_content, last_model
        resp = await chat_fn(message=msg, system_prompt=system_prompt)
        totals["p"] += resp.prompt_tokens
        totals["c"] += resp.completion_tokens
        last_content = resp.content
        last_model = resp.model
        return resp

    def result(content, passed, escalate, rounds, rung):
        """Construct an IterateResult."""
        return IterateResult(
            content=content, passed=passed, escalate=escalate, rounds=rounds,
            winning_rung=rung, model=last_model,
            prompt_tokens=totals["p"], completion_tokens=totals["c"],
            history=history,
        )

    async def run_round(msg):
        """One attempt + gate -> (passed, feedback). A backend error (oMLX down,
        507 out-of-memory, timeout, ...) becomes a failed round so the ladder
        degrades to escalation instead of crashing the tool."""
        try:
            resp = await attempt(msg)
        except Exception as e:
            return False, f"backend error: {e}"
        gr = gate_fn(resp.content)
        return gr.passed, gr.feedback

    # No gate: single local attempt, Claude verifies. A backend error escalates.
    if gate_fn is None:
        try:
            await attempt(message)
        except Exception as e:
            history.append(f"backend error: {e}")
            return result(last_content, False, True, 1, "escalated")
        return result(last_content, None, False, 1, "local")

    rounds = 0

    # Rung 1: active local model, up to max_local_rounds, feeding failures back in.
    for i in range(max_local_rounds):
        rounds += 1
        msg = message if i == 0 else _retry_message(message, history[-1])
        passed, feedback = await run_round(msg)
        if passed:
            return result(last_content, True, False, rounds, "local")
        history.append(feedback)

    # Rung 2: bump to a bigger local model for one attempt (still free).
    if big_model and set_model_fn and get_model_fn:
        previous = get_model_fn()
        try:
            set_model_fn(big_model)
            rounds += 1
            passed, feedback = await run_round(
                _retry_message(message, history[-1] if history else ""))
            if passed:
                return result(last_content, True, False, rounds, "local_big")
            history.append(feedback)
        finally:
            set_model_fn(previous)

    # Rung 3: escalate to Claude with the best local attempt + failure history.
    return result(last_content, False, True, rounds, "escalated")
