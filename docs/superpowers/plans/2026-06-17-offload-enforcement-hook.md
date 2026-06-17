# Offload Enforcement Hook — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `UserPromptSubmit` hook that classifies each prompt on the local model and, for offloadable work, generates the answer locally and injects it for the assistant to verify — closing the ~10× capture gap between eligible (~49–60%) and realized (<10%) offload.

**Architecture:** A pure-stdlib package `mlx_mcp_server/hook/` (urllib + the existing `mlx_mcp_server.gates`, no httpx/yaml/mcp imports) so it starts instantly and fails predictably. Five stages — prefilter → classify → gate+generate → inject → log. A quality gate-fail escalates silently to Claude; an oMLX *transport* failure triggers `omlx restart` and a loud directive that makes the assistant pause and tell the user (never a silent Opus fallback). A separate counts-only decision log feeds capture/escalation dashboard panels.

**Tech Stack:** Python ≥3.11, stdlib only (`urllib`, `json`, `subprocess`, `dataclasses`), reusing `mlx_mcp_server.gates`; pytest + `asyncio_mode=auto` (sync tests here); token-metrics dashboard (prometheus_client gauges/counters).

## Global Constraints

- **Pure stdlib in `mlx_mcp_server/hook/`** — no `httpx`, `yaml`, `mcp`, or other third-party imports; importing `mlx_mcp_server.gates` (stdlib-only) is allowed. Keeps the hook fast to start and dependency-free.
- **The hook NEVER raises to its caller and NEVER hard-blocks the prompt** (no `exit 2`). Every stage is wrapped so failures degrade to a safe outcome.
- **Counts and labels only** in both logs — never prompt text or completion text.
- **Direct HTTP to oMLX only** (never the MCP tool) — no recursion.
- **oMLX transport failure ≠ quality failure.** Transport error (connection refused / timeout / any non-2xx) → Case 2 (loud + restart + pause). A successful call whose output fails the gate → Case 1 (silent escalation to Claude).
- **Default tuning values:** prefilter `min_chars=40`; offload `confidence` cutoff `0.6`. Both are module-level constants, tunable later.
- **Call-log schema (must match `server._append_call_log`):** `{ts, model, category, prompt_tokens, completion_tokens, rounds, winning_rung}` with `winning_rung="local"`.
- **Decision-log schema:** `{ts, decision, category, confidence}`, `decision ∈ {offloaded, passthrough, gate_escalate, infra_error}`.
- Paths: call log `~/.omlx/mlx-call-log.jsonl`; decision log `~/.omlx/hook-decisions.jsonl`.
- Work on branch `offload-enforcement-hook`. Run tests with the dev extras installed (`uv run pytest` from the repo).

---

### Task 1: oMLX transport (`hook/omlx.py`)

**Files:**
- Create: `src/mlx_mcp_server/hook/__init__.py` (empty)
- Create: `src/mlx_mcp_server/hook/omlx.py`
- Test: `tests/test_hook_omlx.py`

**Interfaces:**
- Consumes: nothing (stdlib `urllib`, `json`, `os`).
- Produces:
  - `class OmlxTransportError(Exception)` — raised on any infra-level failure.
  - `@dataclass ChatResult: content: str; prompt_tokens: int; completion_tokens: int`
  - `resolve_omlx() -> tuple[str, str, str]` returning `(base_url, api_key, model)`.
  - `chat(base_url, api_key, model, system, user, *, timeout=120, _opener=urllib.request.urlopen) -> ChatResult`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_hook_omlx.py
import io
import json
import urllib.error
import pytest
from mlx_mcp_server.hook import omlx


def _fake_opener(payload, status=200):
    def opener(req, timeout=None):
        if status >= 400:
            raise urllib.error.HTTPError(req.full_url, status, "err", {}, io.BytesIO(b""))
        class R:
            def read(self_): return json.dumps(payload).encode()
            def __enter__(self_): return self_
            def __exit__(self_, *a): return False
        return R()
    return opener


def test_chat_returns_content_and_token_counts():
    payload = {"choices": [{"message": {"content": "hello"}}],
               "usage": {"prompt_tokens": 11, "completion_tokens": 5}}
    res = omlx.chat("http://x", "k", "m", "sys", "usr", _opener=_fake_opener(payload))
    assert res.content == "hello"
    assert res.prompt_tokens == 11
    assert res.completion_tokens == 5


def test_chat_raises_transport_error_on_5xx():
    with pytest.raises(omlx.OmlxTransportError):
        omlx.chat("http://x", "k", "m", "s", "u", _opener=_fake_opener({}, status=503))


def test_chat_raises_transport_error_on_urlerror():
    def opener(req, timeout=None):
        raise urllib.error.URLError("connection refused")
    with pytest.raises(omlx.OmlxTransportError):
        omlx.chat("http://x", "k", "m", "s", "u", _opener=opener)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_hook_omlx.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mlx_mcp_server.hook'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/mlx_mcp_server/hook/__init__.py
```
(empty file)

```python
# src/mlx_mcp_server/hook/omlx.py
"""Pure-stdlib transport to the local oMLX server for the offload hook.

A transport failure (unreachable / timeout / any non-2xx) is an INFRASTRUCTURE
problem (Case 2), distinct from a quality gate failure. It surfaces as
OmlxTransportError so the orchestrator can restart oMLX and pause — never a
silent fallback to Claude.
"""
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass


class OmlxTransportError(Exception):
    """oMLX unreachable / timeout / non-2xx — an infrastructure failure."""


@dataclass
class ChatResult:
    content: str
    prompt_tokens: int
    completion_tokens: int


def resolve_omlx():
    """Return (base_url, api_key, model): Claude settings → env → defaults; model
    from the runtime override file, else the first model the server reports."""
    base = key = None
    try:
        with open(os.path.expanduser("~/.claude/settings.json")) as fh:
            env = json.load(fh).get("mcpServers", {}).get("mlx", {}).get("env", {})
        base, key = env.get("MLX_BASE_URL"), env.get("MLX_API_KEY")
    except (OSError, ValueError):
        pass
    base = base or os.environ.get("MLX_BASE_URL") or "http://localhost:8000"
    key = key or os.environ.get("MLX_API_KEY") or ""
    return base, key, _resolve_model(base, key)


def _resolve_model(base_url, api_key):
    try:
        m = open(os.path.expanduser("~/.config/mlx-mcp/active_model")).read().strip()
        if m:
            return m
    except OSError:
        pass
    try:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        req = urllib.request.Request(base_url.rstrip("/") + "/v1/models", headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        models = [m["id"] for m in data.get("data", [])]
        return models[0] if models else ""
    except (urllib.error.URLError, OSError, ValueError, KeyError):
        return ""


def chat(base_url, api_key, model, system, user, *, timeout=120,
         _opener=urllib.request.urlopen):
    """POST /v1/chat/completions and return a ChatResult.

    Raises OmlxTransportError on ANY transport failure (URLError, timeout, or
    non-2xx HTTP status) — these are Case-2 infrastructure errors.
    """
    body = {
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "temperature": 0.0, "max_tokens": 2048,
    }
    if model:
        body["model"] = model
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(base_url.rstrip("/") + "/v1/chat/completions",
                                 data=json.dumps(body).encode(), headers=headers,
                                 method="POST")
    try:
        with _opener(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
    except (urllib.error.HTTPError, urllib.error.URLError, OSError, ValueError) as e:
        raise OmlxTransportError(str(e)) from e
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise OmlxTransportError(f"malformed response: {e}") from e
    usage = data.get("usage") or {}
    return ChatResult(content,
                      int(usage.get("prompt_tokens", 0)),
                      int(usage.get("completion_tokens", 0)))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_hook_omlx.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/mlx_mcp_server/hook/__init__.py src/mlx_mcp_server/hook/omlx.py tests/test_hook_omlx.py
git commit -m "feat(hook): oMLX stdlib transport with transport-error signal"
```

---

### Task 2: Prefilter (`hook/prefilter.py`)

**Files:**
- Create: `src/mlx_mcp_server/hook/prefilter.py`
- Test: `tests/test_hook_prefilter.py`

**Interfaces:**
- Produces: `is_trivial(prompt, *, min_chars=40) -> bool`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_hook_prefilter.py
from mlx_mcp_server.hook.prefilter import is_trivial


def test_short_prompt_is_trivial():
    assert is_trivial("ok") is True
    assert is_trivial("   ") is True


def test_control_word_is_trivial_even_if_longer_form():
    assert is_trivial("yes") is True
    assert is_trivial("Continue") is True
    assert is_trivial("thanks!") is True


def test_substantive_prompt_is_not_trivial():
    assert is_trivial("Summarize the following error log and tell me the root cause") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_hook_prefilter.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# src/mlx_mcp_server/hook/prefilter.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_hook_prefilter.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/mlx_mcp_server/hook/prefilter.py tests/test_hook_prefilter.py
git commit -m "feat(hook): trivial-prompt prefilter"
```

---

### Task 3: Classifier (`hook/classify.py`)

**Files:**
- Create: `src/mlx_mcp_server/hook/classify.py`
- Test: `tests/test_hook_classify.py`

**Interfaces:**
- Consumes: a `chat_fn(system, user) -> ChatResult` callable (so tests pass a fake; the orchestrator binds `omlx.chat`).
- Produces:
  - `@dataclass Classification: task_type: str; offloadable: bool; confidence: float`
  - `classify(prompt, chat_fn) -> Classification`
  - module constants `TASK_TYPES`, `OFFLOADABLE_TEXT`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_hook_classify.py
from mlx_mcp_server.hook.classify import classify, Classification
from mlx_mcp_server.hook.omlx import ChatResult


def _chat_returning(text):
    def chat(system, user):
        return ChatResult(text, 10, 4)
    return chat


def test_classify_parses_well_formed_json():
    c = classify("summarize this", _chat_returning(
        '{"task_type":"summarize","offloadable":true,"confidence":0.9}'))
    assert c == Classification("summarize", True, 0.9)


def test_classify_coerces_unknown_task_type_to_other():
    c = classify("x", _chat_returning('{"task_type":"banana","offloadable":true,"confidence":0.8}'))
    assert c.task_type == "other"


def test_classify_falls_back_on_unparseable_response():
    c = classify("x", _chat_returning("I cannot answer that as JSON"))
    assert c == Classification("other", False, 0.0)


def test_classify_extracts_json_embedded_in_prose():
    c = classify("x", _chat_returning(
        'Sure:\n{"task_type":"extract","offloadable":true,"confidence":0.7}\nhope that helps'))
    assert c.task_type == "extract" and c.offloadable is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_hook_classify.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# src/mlx_mcp_server/hook/classify.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_hook_classify.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/mlx_mcp_server/hook/classify.py tests/test_hook_classify.py
git commit -m "feat(hook): single-prompt local classifier"
```

---

### Task 4: Gated generation (`hook/generate.py`)

**Files:**
- Create: `src/mlx_mcp_server/hook/generate.py`
- Test: `tests/test_hook_generate.py`

**Interfaces:**
- Consumes: `mlx_mcp_server.gates.structural_gate`, `executable_gate`, `GateResult`; a `chat_fn(system, user) -> ChatResult`.
- Produces:
  - `@dataclass GenResult: status: str; text: str; prompt_tokens: int; completion_tokens: int` where `status ∈ {"ok","escalate"}`.
  - `gate_for(category, candidate) -> GateResult`
  - `generate(prompt, category, chat_fn) -> GenResult`

**Gate design (avoids false escalations on free-form output):** all categories require `min_len=20`. For `code`, additionally extract any ```python fenced blocks; if present, each must pass `py_compile`. No fenced python block → the `min_len` check alone governs (prose-with-snippets is not force-compiled).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_hook_generate.py
from mlx_mcp_server.hook.generate import generate, gate_for, GenResult
from mlx_mcp_server.hook.omlx import ChatResult


def _seq_chat(*replies):
    calls = {"i": 0}
    def chat(system, user):
        r = replies[min(calls["i"], len(replies) - 1)]
        calls["i"] += 1
        return ChatResult(r, 7, 9)
    return chat


def test_gate_for_text_passes_long_enough():
    assert gate_for("summarize", "This is a sufficiently long summary line.").passed


def test_gate_for_text_fails_too_short():
    assert gate_for("summarize", "ok").passed is False


def test_gate_for_code_fails_uncompilable_python_block():
    bad = "Here:\n```python\ndef f( : pass\n```"
    assert gate_for("code", bad).passed is False


def test_gate_for_code_passes_compilable_python_block():
    good = "Here is a stub:\n```python\ndef f():\n    pass\n```"
    assert gate_for("code", good).passed is True


def test_generate_ok_on_first_pass():
    g = generate("summarize x", "summarize", _seq_chat("A nice long enough summary of x."))
    assert g.status == "ok"
    assert "summary" in g.text


def test_generate_escalates_after_two_gate_failures():
    g = generate("summarize x", "summarize", _seq_chat("no", "still"))
    assert g.status == "escalate"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_hook_generate.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# src/mlx_mcp_server/hook/generate.py
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
    status: str  # "ok" | "escalate"
    text: str
    prompt_tokens: int
    completion_tokens: int


def gate_for(category, candidate):
    base = structural_gate(candidate, min_len=_MIN_LEN)
    if not base.passed:
        return base
    if category == "code":
        for block in _PY_BLOCK.findall(candidate):
            r = executable_gate(
                block,
                f'{sys.executable} -c "import py_compile,sys; py_compile.compile(sys.argv[1], doraise=True)" "$CANDIDATE_FILE"',
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_hook_generate.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add src/mlx_mcp_server/hook/generate.py tests/test_hook_generate.py
git commit -m "feat(hook): gated local generation with retry-then-escalate"
```

---

### Task 5: Logs (`hook/logs.py`)

**Files:**
- Create: `src/mlx_mcp_server/hook/logs.py`
- Test: `tests/test_hook_logs.py`

**Interfaces:**
- Produces:
  - `CALL_LOG_PATH`, `DECISIONS_PATH` (module constants under `~/.omlx/`)
  - `append_call_log(model, category, prompt_tokens, completion_tokens, *, rounds=1, path=CALL_LOG_PATH, now_fn=...) -> None`
  - `append_decision(decision, category, confidence, *, path=DECISIONS_PATH, now_fn=...) -> None`
  - `DECISIONS = {"offloaded","passthrough","gate_escalate","infra_error"}`

Both writers are best-effort (never raise) and write **counts/labels only**.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_hook_logs.py
import json
from mlx_mcp_server.hook import logs


def test_append_call_log_matches_server_schema(tmp_path):
    p = tmp_path / "call.jsonl"
    logs.append_call_log("M", "summarize", 10, 5, path=str(p), now_fn=lambda: "T")
    row = json.loads(p.read_text().strip())
    assert row == {"ts": "T", "model": "M", "category": "summarize",
                   "prompt_tokens": 10, "completion_tokens": 5,
                   "rounds": 1, "winning_rung": "local"}


def test_append_decision_writes_counts_only(tmp_path):
    p = tmp_path / "dec.jsonl"
    logs.append_decision("offloaded", "code", 0.8, path=str(p), now_fn=lambda: "T")
    row = json.loads(p.read_text().strip())
    assert row == {"ts": "T", "decision": "offloaded", "category": "code",
                   "confidence": 0.8}
    assert "text" not in row and "content" not in row and "prompt" not in row


def test_writers_never_raise_on_bad_path():
    # directory that cannot be created -> silently ignored
    logs.append_decision("offloaded", "code", 0.1, path="/proc/nonexistent/x.jsonl")
    logs.append_call_log("M", "code", 1, 1, path="/proc/nonexistent/x.jsonl")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_hook_logs.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# src/mlx_mcp_server/hook/logs.py
"""Stage 4: append counts-only records. Never stores prompt/response text."""
import json
import os
from datetime import datetime, timezone

CALL_LOG_PATH = os.path.expanduser("~/.omlx/mlx-call-log.jsonl")
DECISIONS_PATH = os.path.expanduser("~/.omlx/hook-decisions.jsonl")
DECISIONS = {"offloaded", "passthrough", "gate_escalate", "infra_error"}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _append(path, rec):
    try:
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(path, "a") as fh:
            fh.write(json.dumps(rec) + "\n")
    except OSError:
        pass


def append_call_log(model, category, prompt_tokens, completion_tokens, *,
                    rounds=1, path=CALL_LOG_PATH, now_fn=_now):
    """Same schema as server._append_call_log so the savings panel reads it."""
    _append(path, {
        "ts": now_fn(),
        "model": model or "",
        "category": category or "other",
        "prompt_tokens": int(prompt_tokens or 0),
        "completion_tokens": int(completion_tokens or 0),
        "rounds": int(rounds or 1),
        "winning_rung": "local",
    })


def append_decision(decision, category, confidence, *,
                    path=DECISIONS_PATH, now_fn=_now):
    """Counts-only routing decision for capture/escalation panels."""
    _append(path, {
        "ts": now_fn(),
        "decision": decision,
        "category": category or "other",
        "confidence": round(float(confidence or 0.0), 3),
    })
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_hook_logs.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/mlx_mcp_server/hook/logs.py tests/test_hook_logs.py
git commit -m "feat(hook): counts-only call + decision logs"
```

---

### Task 6: Restart (`hook/restart.py`)

**Files:**
- Create: `src/mlx_mcp_server/hook/restart.py`
- Test: `tests/test_hook_restart.py`

**Interfaces:**
- Produces:
  - `@dataclass RestartOutcome: healthy: bool; detail: str`
  - `restart_omlx(base_url, *, run_fn=subprocess.run, health_fn=...) -> RestartOutcome`

`restart_omlx` runs `omlx restart` (≤15s), then checks `base_url/health`. If still unhealthy, captures `omlx diagnose` output into `detail`. Never raises.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_hook_restart.py
import subprocess
from mlx_mcp_server.hook.restart import restart_omlx, RestartOutcome


class _Run:
    def __init__(self, diagnose_out="diag-output"):
        self.calls = []
        self.diagnose_out = diagnose_out
    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        out = self.diagnose_out if "diagnose" in cmd else "restarted"
        return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")


def test_restart_healthy_after_restart():
    run = _Run()
    out = restart_omlx("http://x", run_fn=run, health_fn=lambda b: True)
    assert out.healthy is True
    assert any("restart" in c for c in run.calls)
    # diagnose is NOT run when healthy
    assert not any("diagnose" in c for c in run.calls)


def test_restart_still_down_captures_diagnose():
    run = _Run(diagnose_out="port 8000 not listening")
    out = restart_omlx("http://x", run_fn=run, health_fn=lambda b: False)
    assert out.healthy is False
    assert "port 8000 not listening" in out.detail


def test_restart_never_raises_when_run_fn_explodes():
    def boom(cmd, **kw):
        raise OSError("omlx not found")
    out = restart_omlx("http://x", run_fn=boom, health_fn=lambda b: False)
    assert isinstance(out, RestartOutcome) and out.healthy is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_hook_restart.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# src/mlx_mcp_server/hook/restart.py
"""Case 2 recovery: attempt `omlx restart`, then report health / diagnose."""
import json
import subprocess
import urllib.request
from dataclasses import dataclass


@dataclass
class RestartOutcome:
    healthy: bool
    detail: str


def _default_health(base_url):
    try:
        with urllib.request.urlopen(base_url.rstrip("/") + "/health", timeout=5) as r:
            return json.loads(r.read().decode()).get("status") == "healthy"
    except Exception:
        return False


def restart_omlx(base_url, *, run_fn=subprocess.run, health_fn=_default_health):
    """Run `omlx restart`, poll health once; if still down, capture `omlx diagnose`.
    Never raises."""
    try:
        run_fn(["omlx", "restart"], capture_output=True, text=True, timeout=15)
    except Exception as e:  # noqa: BLE001 - best-effort recovery, must not raise
        return RestartOutcome(False, f"`omlx restart` failed to run: {e}")
    if health_fn(base_url):
        return RestartOutcome(True, "oMLX is healthy again after restart.")
    try:
        diag = run_fn(["omlx", "diagnose"], capture_output=True, text=True, timeout=15)
        detail = (getattr(diag, "stdout", "") or getattr(diag, "stderr", "") or "").strip()
    except Exception as e:  # noqa: BLE001
        detail = f"`omlx diagnose` failed: {e}"
    return RestartOutcome(False, detail[:1500] or "still down; no diagnose output")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_hook_restart.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/mlx_mcp_server/hook/restart.py tests/test_hook_restart.py
git commit -m "feat(hook): omlx restart + diagnose recovery for Case 2"
```

---

### Task 7: Orchestrator (`hook/run.py` + `hook/__main__.py`)

**Files:**
- Create: `src/mlx_mcp_server/hook/run.py`
- Create: `src/mlx_mcp_server/hook/__main__.py`
- Test: `tests/test_hook_run.py`

**Interfaces:**
- Consumes: every prior module.
- Produces:
  - `CONFIDENCE_CUTOFF = 0.6`
  - `run(event, *, deps=None) -> dict | None` — returns the stdout JSON dict to emit, or `None` for "emit nothing". Never raises.
  - `@dataclass Deps` bundling the injectable functions (`resolve, classify, generate, restart, append_call_log, append_decision, is_trivial`) with real defaults, so tests inject fakes.
  - `main() -> int` in `__main__.py` reading stdin / writing stdout.

**Behavior (the five stages):**
1. `is_trivial(prompt)` → return `None` (no log).
2. resolve oMLX; bind `chat = lambda s, u: omlx.chat(base, key, model, s, u)`.
3. `classify`; on `OmlxTransportError` → Case 2. If not offloadable or `confidence < CONFIDENCE_CUTOFF` → `append_decision("passthrough", …)`, return `None`.
4. `generate`; on `OmlxTransportError` → Case 2. If `status=="escalate"` → `append_decision("gate_escalate", …)`, return `None`.
5. `ok` → `append_call_log(...)` + `append_decision("offloaded", …)` → return the `additionalContext` injection dict.
- Case 2 → `restart_omlx`, `append_decision("infra_error", …)`, return the loud-directive injection dict.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_hook_run.py
from mlx_mcp_server.hook import run as runmod
from mlx_mcp_server.hook.run import run, Deps
from mlx_mcp_server.hook.classify import Classification
from mlx_mcp_server.hook.generate import GenResult
from mlx_mcp_server.hook.restart import RestartOutcome
from mlx_mcp_server.hook.omlx import OmlxTransportError


def _deps(**over):
    rec = {"decisions": [], "calls": []}
    base = dict(
        resolve=lambda: ("http://x", "k", "M"),
        classify=lambda prompt, chat: Classification("summarize", True, 0.9),
        generate=lambda prompt, cat, chat: GenResult("ok", "LOCAL ANSWER", 10, 5),
        restart=lambda base_url: RestartOutcome(True, "healthy"),
        append_call_log=lambda *a, **k: rec["calls"].append((a, k)),
        append_decision=lambda decision, cat, conf, **k: rec["decisions"].append(decision),
        is_trivial=lambda p: False,
    )
    base.update(over)
    return Deps(**base), rec


def test_trivial_prompt_emits_nothing():
    deps, rec = _deps(is_trivial=lambda p: True)
    assert run({"prompt": "ok"}, deps=deps) is None
    assert rec["decisions"] == []


def test_offloadable_injects_local_draft_and_logs():
    deps, rec = _deps()
    out = run({"prompt": "summarize this long thing here please"}, deps=deps)
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert "LOCAL DRAFT" in ctx and "LOCAL ANSWER" in ctx
    assert rec["decisions"] == ["offloaded"]
    assert len(rec["calls"]) == 1


def test_low_confidence_passes_through():
    deps, rec = _deps(classify=lambda p, c: Classification("summarize", True, 0.3))
    assert run({"prompt": "x" * 80}, deps=deps) is None
    assert rec["decisions"] == ["passthrough"]


def test_gate_escalate_passes_through_silently():
    deps, rec = _deps(generate=lambda p, cat, c: GenResult("escalate", "", 1, 1))
    assert run({"prompt": "x" * 80}, deps=deps) is None
    assert rec["decisions"] == ["gate_escalate"]


def test_transport_error_triggers_loud_pause_directive():
    def boom(prompt, chat):
        raise OmlxTransportError("connection refused")
    deps, rec = _deps(classify=boom)
    out = run({"prompt": "x" * 80}, deps=deps)
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert "PAUSE" in ctx and "oMLX" in ctx
    assert rec["decisions"] == ["infra_error"]


def test_run_never_raises_on_unexpected_error():
    def boom(prompt, chat):
        raise RuntimeError("unexpected")
    deps, rec = _deps(classify=boom)
    # A non-transport error is swallowed by the outer guard -> emit nothing.
    assert run({"prompt": "x" * 80}, deps=deps) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_hook_run.py -v`
Expected: FAIL — `ImportError` (no `run`/`Deps`)

- [ ] **Step 3: Write minimal implementation**

```python
# src/mlx_mcp_server/hook/run.py
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
    resolve: Callable
    classify: Callable
    generate: Callable
    restart: Callable
    append_call_log: Callable
    append_decision: Callable
    is_trivial: Callable


def _default_deps():
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
    return {"hookSpecificOutput": {"hookEventName": _EVENT_NAME, "additionalContext": text}}


def _case2(deps, base_url, category):
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
```

```python
# src/mlx_mcp_server/hook/__main__.py
"""Entry point wired as a UserPromptSubmit hook. Reads the event JSON on stdin,
emits an optional context-injection JSON on stdout. Always exits 0."""
import json
import sys

from .run import run


def main():
    try:
        event = json.load(sys.stdin)
    except Exception:  # noqa: BLE001
        return 0
    out = run(event)
    if out:
        sys.stdout.write(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_hook_run.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add src/mlx_mcp_server/hook/run.py src/mlx_mcp_server/hook/__main__.py tests/test_hook_run.py
git commit -m "feat(hook): orchestrator + stdin/stdout entry point"
```

---

### Task 8: Console-script entry point + README + settings snippet

**Files:**
- Modify: `pyproject.toml` (add a `[project.scripts]` entry + bump version)
- Modify: `README.md` (document the hook + the manual settings.json wiring)
- Test: `tests/test_hook_entrypoint.py`

**Interfaces:**
- Produces: a `mlx-offload-hook` console script resolving to `mlx_mcp_server.hook.__main__:main`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_hook_entrypoint.py
import tomllib
from pathlib import Path


def test_console_script_registered():
    data = tomllib.loads(Path("pyproject.toml").read_text())
    assert data["project"]["scripts"]["mlx-offload-hook"] == "mlx_mcp_server.hook.__main__:main"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_hook_entrypoint.py -v`
Expected: FAIL — KeyError `'mlx-offload-hook'`

- [ ] **Step 3: Add the script + bump version**

In `pyproject.toml`, under `[project.scripts]` (which currently has only `mlx-mcp-server`):

```toml
[project.scripts]
mlx-mcp-server = "mlx_mcp_server.server:main"
mlx-offload-hook = "mlx_mcp_server.hook.__main__:main"
```

Bump `version = "0.2.4"` → `version = "0.3.0"` (new feature surface).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_hook_entrypoint.py -v`
Expected: PASS

- [ ] **Step 5: Document in README**

Add a `## Offload enforcement hook` section to `README.md` containing:
- What it does (classifies each prompt locally; injects a local draft for offloadable work; logs counts only).
- The two failure modes (silent quality escalation vs. loud oMLX-infra pause).
- The **manual** wiring snippet for `~/.claude/settings.json` (the user adds this; the installer does not edit settings automatically):

````markdown
```json
{
  "hooks": {
    "UserPromptSubmit": [
      { "hooks": [ { "type": "command", "command": "mlx-offload-hook" } ] }
    ]
  }
}
```
````
- A note: `mlx-offload-hook` must be on `PATH` (it is, via `uv tool install mlx-mcp-server` → `~/.local/bin`), and it reads oMLX creds from `~/.claude/settings.json` → `mcpServers.mlx.env`.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml README.md tests/test_hook_entrypoint.py
git commit -m "feat(hook): console-script entry point + README wiring; bump 0.3.0"
```

---

### Task 9: Dashboard — capture & escalation panels (token-metrics)

**Files:**
- Modify: `/Users/brice/Claude Code work/token-metrics/tools/collect.py` (add `read_hook_decisions`)
- Modify: `/Users/brice/Claude Code work/token-metrics/tools/exporter.py` (add a decision counter gauge)
- Modify: `/Users/brice/Claude Code work/token-metrics/tools/test_eval_metrics.py` (add tests) — or a new `test_hook_metrics.py` in the same dir
- Modify: `/Users/brice/Claude Code work/token-metrics/dashboard/build_dashboard.py` (add a row) and regenerate `token-savings.json`

**Interfaces:**
- Consumes: `~/.omlx/hook-decisions.jsonl` (schema `{ts, decision, category, confidence}`).
- Produces:
  - `read_hook_decisions(path) -> dict[(decision, category), int]` (counts).
  - Prometheus gauge `mlx_hook_decision_total{decision,category}`.
  - Dashboard PromQL: capture rate = `sum(mlx_hook_decision_total{decision="offloaded"}) / sum(mlx_hook_decision_total{decision=~"offloaded|gate_escalate|infra_error"})`; escalation rate = `sum(mlx_hook_decision_total{decision="gate_escalate"}) / sum(mlx_hook_decision_total{decision=~"offloaded|gate_escalate"})`.

- [ ] **Step 1: Write the failing test**

```python
# token-metrics/tools/test_hook_metrics.py
import json
from tools.collect import read_hook_decisions


def test_read_hook_decisions_counts_by_decision_and_category(tmp_path):
    p = tmp_path / "hook-decisions.jsonl"
    rows = [
        {"ts": "T", "decision": "offloaded", "category": "summarize", "confidence": 0.9},
        {"ts": "T", "decision": "offloaded", "category": "summarize", "confidence": 0.8},
        {"ts": "T", "decision": "gate_escalate", "category": "code", "confidence": 0.7},
        {"ts": "T", "decision": "passthrough", "category": "reasoning", "confidence": 0.1},
    ]
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    counts = read_hook_decisions(str(p))
    assert counts[("offloaded", "summarize")] == 2
    assert counts[("gate_escalate", "code")] == 1
    assert counts[("passthrough", "reasoning")] == 1


def test_read_hook_decisions_missing_file_is_empty():
    assert read_hook_decisions("/no/such/file.jsonl") == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "/Users/brice/Claude Code work/token-metrics" && uv run pytest tools/test_hook_metrics.py -v` (or `python3 -m pytest`)
Expected: FAIL — `ImportError: cannot import name 'read_hook_decisions'`

- [ ] **Step 3: Implement `read_hook_decisions` in `collect.py`**

```python
def read_hook_decisions(path):
    """Count hook routing decisions by (decision, category). Missing file -> {}."""
    import collections
    counts = collections.Counter()
    try:
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                counts[(d.get("decision", "?"), d.get("category", "?"))] += 1
    except OSError:
        return {}
    return dict(counts)
```

Add a `hook_decisions: str = ""` field to the `Paths` dataclass (default keeps back-compat), defaulting to `~/.omlx/hook-decisions.jsonl` in `DEFAULT_PATHS`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "/Users/brice/Claude Code work/token-metrics" && uv run pytest tools/test_hook_metrics.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Add the exporter gauge**

In `exporter.py`, alongside the eval gauges, add:

```python
hook_dec = GaugeMetricFamily(
    "mlx_hook_decision_total", "Offload hook routing decisions",
    labels=["decision", "category"])
for (decision, category), n in read_hook_decisions(paths.hook_decisions).items():
    hook_dec.add_metric([decision, category], n)
yield hook_dec
```

Add `hook_decisions` to `DEFAULT_PATHS`.

- [ ] **Step 6: Add the dashboard row + regenerate**

In `build_dashboard.py`, add a `▸ Offload Capture` row with two stat panels (capture rate, escalation rate) using the PromQL above and a timeseries of `mlx_hook_decision_total` by decision. Then:

```bash
cd "/Users/brice/Claude Code work/token-metrics" && python3 dashboard/build_dashboard.py
```

- [ ] **Step 7: Commit (token-metrics repo)**

```bash
cd "/Users/brice/Claude Code work/token-metrics"
git add tools/collect.py tools/exporter.py tools/test_hook_metrics.py dashboard/build_dashboard.py dashboard/token-savings.json
git commit -m "feat: offload-hook capture + escalation dashboard panels"
```

---

## Final integration step (after all tasks pass)

- [ ] Run the whole mlx-mcp-server suite: `cd "/Users/brice/Claude Code work/mlx-mcp-server" && uv run pytest -q` — expect all green.
- [ ] Manually smoke-test the hook end-to-end:
  ```bash
  echo '{"prompt":"Summarize: the cat sat on the mat, then it left."}' | mlx-offload-hook
  ```
  Expect a JSON object with `additionalContext` containing `LOCAL DRAFT`, and a new row in `~/.omlx/hook-decisions.jsonl` (`decision":"offloaded"`).
- [ ] Smoke-test the Case-2 path with oMLX stopped:
  ```bash
  omlx stop
  echo '{"prompt":"Summarize: the cat sat on the mat, then it left."}' | mlx-offload-hook
  omlx start
  ```
  Expect `additionalContext` containing `PAUSE` and a `infra_error` decision row.
- [ ] Report the smoke-test results to Brice; he adds the `~/.claude/settings.json` snippet and restarts Claude Code (loading the hook is his step, like the command-file restart).
