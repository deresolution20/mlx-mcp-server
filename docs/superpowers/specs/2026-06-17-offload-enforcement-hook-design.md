# Offload Enforcement Hook — Design

**Date:** 2026-06-17
**Status:** Approved (design); pending implementation plan
**Repo:** `mlx-mcp-server`

## Problem

The MLX offload tooling exists, but the savings are negligible: **$0.92 saved to
date against $720 of Claude spend.** Investigation found the cause is not the
savings formula — it is **capture**:

- The offload log (`~/.omlx/mlx-call-log.jsonl`) holds only **72 events / ~5,300
  tokens**, and **69 of 72 are category `other`** (trivial pings). Real
  boilerplate/summarize/extract/review offloads are essentially zero.
- The offload-opportunity estimator, run over the last 7 days of transcripts
  (278 prompts), found **136 (49%) were offloadable** — ~$3.46/week of Claude
  output spend at the conservative Sonnet $15/1M floor (an undercount: it values
  at Sonnet not Opus, credits only the direct-reply turn, and marks all 79 `code`
  prompts as mostly non-offloadable even though the 30B passed the entire code
  eval suite 24/24 — true eligible share is ~60%+).
- The dashboard's "saved this week" is **$0.26**, so we realize **under 10% of
  eligible savings** — a ~10× capture gap.

**Root cause:** the offload policy is advisory (a standing `CLAUDE.md`
instruction). Routing depends on the assistant *voluntarily* calling the local
model mid-task, and in practice it forgets. Advisory policy already failed once;
that is the current $0.92. To improve drastically, routing must be **enforced,
not intended.**

## Goal

A `UserPromptSubmit` hook that, for every prompt, classifies it on the **local
model**, and for offloadable work **generates the answer locally and injects it**
into the assistant's context to verify rather than regenerate. This converts the
49–60% eligible share from intention into realized local generation, logged with
its real category so the savings dashboard reflects it.

## Scope

**In scope (v1):**
- A standalone, pure-stdlib hook module shipped in `mlx-mcp-server`.
- Local classification + gated local generation + context injection + logging.
- Offloadable categories: `summarize`, `extract`, `classify`, `draft`, and
  **single-file / single-function `code`** (the 30B handles these).
- A loud, pausing failure path for oMLX infrastructure errors (with `omlx
  restart` attempt).
- A new counts-only decision log + capture-rate / escalation-rate dashboard
  panels.

**Out of scope (deferred, each its own spec):**
- **mission-control / PII** — the hook is global but v1 uses a single
  verify-and-fix contract on the AIOS/general side only. PII-mandatory-local with
  a trust-and-ship contract is a separate spec (preserves the hard
  employer/side-gig data-separation rule).
- **Internal tool-loop offload** — the hook only sees *user-submitted* prompts,
  so it captures user-initiated offloadable work, not generation that happens
  inside the assistant's own tool loop. v2.
- **Post-injection quality escalation signal** — if a local draft passes the gate
  but the assistant still finds it weak and redoes it, v1 does not capture that
  automatically (no signal back from the main loop). Escalation is measured only
  by gate failures the hook can observe. v2.
- **Auto-wiring into `~/.claude/settings.json`** — the hook ships in the repo;
  registering it is a documented manual snippet the user adds. (Auto-editing
  settings.json is deliberately avoided.)

## Approach

**Standalone stdlib hook, shipped in the `mlx-mcp-server` repo** (chosen over
importing the live `iterate` machinery). A pure-stdlib module (`mlx_mcp_server/
hook/`) with zero heavy imports so it starts instantly and fails predictably. It
reuses the *patterns* already proven in `token-metrics/tools/offload_opportunity.py`
(`_mlx_credentials`, `make_mlx_chat`, the classifier prompt) and talks to oMLX
over plain HTTP. The one valuable idea borrowed from the `iterate` tool — a
lightweight **inline gate** — is reimplemented locally (structural + executable)
rather than imported, so local output self-checks before injection.

## Architecture

`UserPromptSubmit` fires → hook receives `{prompt, cwd, session_id, ...}` JSON on
stdin → five stages, in order:

1. **Prefilter (no network).** Skip trivial prompts — very short (below a
   character threshold) or control words ("yes", "continue", "go", "thanks",
   etc.). These pass through instantly (exit 0, no injection). Everything else
   proceeds.

2. **Classify (1 local call).** The local model returns
   `{task_type, offloadable, confidence}` for the single prompt. `task_type` is
   one of `summarize/extract/classify/draft/code/reasoning/other`. Single-file /
   single-function code is judged `offloadable=true`; multi-file / architectural
   work classifies as `reasoning` (not offloadable). Bounded timeout.

3. **Generate (1 local call, gated).** If `offloadable` and confidence is high
   enough, the local model produces the answer. An **inline gate** checks it:
   structural (min length, JSON shape when applicable) and, for code, executable
   (`py_compile` for Python). Pass → continue to inject. Fail → retry once; fail
   again → **quality escalation** (Case 1 below).

4. **Inject.** Emit on stdout:
   ```json
   {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
     "additionalContext": "LOCAL DRAFT (category=<cat>, model=<id>):\n<output>\n\nVerify against the request; fix or escalate if inadequate, otherwise use it — do not regenerate from scratch."}}
   ```

5. **Log.** Append the offload to `~/.omlx/mlx-call-log.jsonl` using the existing
   schema (`ts, model, category, prompt_tokens, completion_tokens`) so the
   savings panel rises automatically. Also append a counts-only record to a new
   `~/.omlx/hook-decisions.jsonl`:
   `{ts, decision, category, confidence}` where `decision` ∈
   `offloaded | passthrough | gate_escalate | infra_error`. No prompt or
   completion text is ever stored in either log.

**Recursion guard:** the hook calls oMLX over **direct HTTP**, never via the MCP
tool, so it cannot recurse into itself.

## Failure handling

Two cases of "local couldn't do it", treated oppositely:

**Case 1 — Quality escalation (normal, silent).** oMLX is healthy but the local
output failed the gate after one retry — the model genuinely can't do *this*
task. Inject nothing (exit 0), log `gate_escalate`, the assistant proceeds on
Claude **without interrupting the user.** This is the ladder working as intended.

**Case 2 — Infrastructure error (abnormal, loud + pause).** A connection error,
timeout, or 5xx on the classify-or-generate HTTP call — the *server* is broken,
not a quality issue. The hook:
1. Runs `omlx restart` (bounded ~15s) and polls `/health` once.
2. Injects a loud directive into context:
   *"oMLX errored on an offloadable prompt. Restart attempted — outcome:
   [healthy again / still down; `omlx diagnose`: …]. Do NOT silently proceed on
   Opus. Tell Brice, report the restart outcome, and PAUSE for his call."*
3. Logs `infra_error`.

The assistant, on seeing that directive, **stops and surfaces it** ("oMLX threw
an error; I ran `omlx restart` — it's back / still down with this diagnose
output. Retry the offload, or do you want to look first?") and waits. The user is
never left with Opus quietly burning tokens because the local server fell over.

Distinguishing the cases: a transport error (connection refused / timeout / 5xx)
on the HTTP call = Case 2 (infra). A *successful* call whose output fails the
gate = Case 1 (quality).

## Components (units)

- `mlx_mcp_server/hook/credentials.py` — resolve oMLX base URL + API key + active
  model (mirrors `offload_opportunity._mlx_credentials` / `_resolve_model`).
- `mlx_mcp_server/hook/classify.py` — single-prompt classifier (prompt template +
  response coercion to `{task_type, offloadable, confidence}`).
- `mlx_mcp_server/hook/gate.py` — inline structural + executable gate for a
  candidate string.
- `mlx_mcp_server/hook/generate.py` — gated local generation (generate → gate →
  retry once → escalate).
- `mlx_mcp_server/hook/logs.py` — append to `mlx-call-log.jsonl` (existing
  schema) and `hook-decisions.jsonl` (counts only).
- `mlx_mcp_server/hook/restart.py` — `omlx restart` + `/health` poll +
  `omlx diagnose` capture for Case 2.
- `mlx_mcp_server/hook/__main__.py` — orchestrator: read stdin, run the five
  stages, classify transport errors as Case 2, emit stdout, never raise.
- `token-metrics/tools/collect.py` + `exporter.py` + `dashboard/build_dashboard.py`
  — read `hook-decisions.jsonl`; add capture-rate and escalation-rate gauges +
  a dashboard row.

Each unit takes injectable dependencies (e.g. a `chat_fn`, a clock, a logs path)
so it is unit-testable without a live oMLX.

## Data flow

```
user prompt ─► UserPromptSubmit hook (stdin JSON)
   ├─ prefilter ──(trivial)──► exit 0, no injection
   ├─ classify (local) ──(not offloadable)──► exit 0, log passthrough
   ├─ generate+gate (local)
   │     ├─ pass ─► inject LOCAL DRAFT, log offloaded (+ mlx-call-log)
   │     └─ gate fail x2 ─► exit 0, log gate_escalate   [Case 1]
   └─ transport error ─► omlx restart + health poll ─► inject loud directive,
                          log infra_error               [Case 2]
```

## Error handling principles

- The hook **never raises** to the caller and never blocks the prompt (no exit 2)
  except via the deliberate Case 2 injected directive (which is exit 0 + context,
  not a hard block).
- Any unexpected exception in a stage → treat as Case 2 if it is transport-shaped,
  else fall through to a safe passthrough (exit 0, log `infra_error` with a
  generic reason) — never a silent Opus fallback for a *server* problem.
- All timeouts are bounded so the hook cannot hang the prompt indefinitely.

## Testing

Pure-stdlib, dependency-injected units → unit tests with a mocked `chat_fn` and
fake clock (mirrors existing `eval/` and `token-metrics` test style):
- classify: JSON parsing, coercion, bad/short response → `other`/non-offloadable.
- gate: structural pass/fail, `py_compile` pass/fail, retry-then-escalate.
- generate: offloadable→inject path; gate-fail→escalate path.
- logs: both files get the exact allowed keys; **no text fields** ever written.
- restart: `omlx restart` invoked + health-poll outcome parsed (subprocess mocked).
- orchestrator: prefilter skip; offloaded happy path emits correct stdout JSON;
  transport error → Case 2 directive; never raises.
- dashboard/exporter: capture-rate + escalation-rate computed from a fixture
  `hook-decisions.jsonl`.

## Privacy

Both logs contain **counts and labels only** — never prompt text or completion
text. The hook runs entirely on-machine. (mission-control/PII is out of scope for
v1 by design.)

## Success criteria

- Realized weekly capture rises from <10% toward the offloadable share (49–60%),
  visible as the savings panel climbing and a capture-rate panel.
- oMLX infrastructure failures surface to the user with a restart attempt and a
  pause — never a silent Opus fallback.
- Quality escalations proceed on Claude silently and are counted, so we can see
  per-category whether a category is secretly not offloadable.
