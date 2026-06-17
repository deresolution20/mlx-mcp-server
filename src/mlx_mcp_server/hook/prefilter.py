"""Stage 0: skip prompts too trivial to bother offloading (no network)."""

_CONTROL = {
    "yes", "no", "y", "n", "ok", "okay", "yep", "yeah", "nope",
    "go", "stop", "continue", "proceed", "next", "done", "thanks",
    "thank you", "thx", "sure", "please", "do it",
}


def is_trivial(prompt, *, min_chars=40):
    """True if the prompt is a bare acknowledgement/control word, or shorter than
    min_chars after stripping punctuation/whitespace."""
    s = (prompt or "").strip()
    bare = s.lower().rstrip("!.?").strip()
    if bare in _CONTROL:
        return True
    return len(s) < min_chars
