# Internal Tool-Loop Offload (Phase 2) — Design

**Date:** 2026-06-17
**Status:** Approved (design); pending implementation plan
**Repos:** `mlx-mcp-server` (gate hook + nudge), `token-metrics` (dashboard)

## Problem

The Phase 1 enforcement hook (`UserPromptSubmit`) is live and correct, but
savings barely moved ($0.92 → $0.995 to date). Diagnosis from `~/.omlx/` logs on
2026-06-17:

- The hook fired only 8× (2 offloaded, 5 correctly-passed-through reasoning/
  conversational prompts, 1 drill). It works; it just has little to act on.
- The call log holds 84 entries today but ~2,302 completion tokens — 79/84 are
  trivial ~8-token health-check pings. Real offloaded *work* ≈ 5 entries.

The dominant token cost is the **assistant's own tool-loop generation** — code,
specs, plans, drafts produced while working — which runs on **Opus** (the $888
Claude spend climbing). The `UserPromptSubmit` hook only sees **user prompts**, a
thin slice; it deliberately never touched internal generation (Phase 1's deferred
"internal tool-loop offload"). The data proves that deferred piece is where
essentially all the savings live. No prompt-hook tuning moves the needle while
the assistant's generation stays on Claude.

## Goal

Make the assistant's own offloadable generation **visible and gently pressured**,
without a hard interception point (there is no "Claude is about to generate"
event). Posture is **hybrid: measure + soft gate** — no blocking.

## Scope

**In scope:**
- A new pure-stdlib `PreToolUse` hook (`mlx-offload-gate`) that detects a large
  code/doc write with no local offload that turn and logs a counts-only
  `missed_offload` (non-blocking).
- A turn-boundary marker written by the existing `UserPromptSubmit` hook.
- A small nudge added to the `UserPromptSubmit` hook surfacing the session's
  offload counts.
- token-metrics: a "Local generation share" panel and a "Missed offloads" panel
  (`missed_offload` added to the decisions set + exporter).

**Out of scope (deferred):**
- **Phase 2b — local-classifier refinement** of the gate (ask the local model
  "was this offloadable?" before warning). Only if the heuristic proves noisy.
- **Hard blocking** — explicitly rejected; the gate always allows the write.
- **Auto-wiring `settings.json`** — the `PreToolUse` matcher is a documented
  manual snippet the user adds (installer never edits settings).
- The behavior change itself (assistant actually routing generation to local) is
  **discipline, not code** — it starts immediately, independent of this build.

## Approach

Two cooperating hooks sharing a tiny state file, plus dashboard panels over data
already collected.

**Why a heuristic, not a classifier (v1):** the gate must run on every
`Write`/`Edit` with zero added latency and no extra model calls. A size +
offload-this-turn heuristic is cheap and good enough for a *soft* signal; the
precise classifier is Phase 2b if warnings prove noisy.

**Why the ratio is free:** `token-metrics/tools/collect.py::parse_transcripts`
already accumulates Claude `output_tokens` per project (the source of the
"Claude spent" panel), and `mlx-call-log.jsonl` is the local side. The local
generation share is a PromQL expression over existing gauges — no new ingestion.

## Architecture

```
user prompt ─► UserPromptSubmit hook
                 ├─ (existing 5 stages: classify/generate/inject/log)
                 ├─ NEW: stamp ~/.omlx/turn-state.json {turn_started_ts}
                 └─ NEW: inject nudge "session: N offloads, M missed"

assistant Write/Edit/MultiEdit ─► PreToolUse hook (mlx-offload-gate)
   ├─ content large? (new file OR len ≥ ~1200 chars)            no ─► allow, silent
   ├─ any mlx-call-log entry with ts ≥ turn_started_ts?         yes ─► allow, silent
   └─ large AND none offloaded this turn ─► log missed_offload, allow + soft warning

token-metrics ─► "Local generation share" = offload_ctok / (offload_ctok + claude_output)
              ─► "Missed offloads" = mlx_hook_decision_total{decision="missed_offload"}
```

## Components (units)

- `mlx_mcp_server/hook/turnstate.py` — `stamp(ts, *, path)` and
  `started_ts(*, path) -> str|None` for `~/.omlx/turn-state.json`. Best-effort,
  never raises.
- `mlx_mcp_server/hook/gate.py` — the PreToolUse decision:
  - `written_size(tool_name, tool_input) -> int` (len of `content` for Write,
    `new_string` for Edit, summed `edits` for MultiEdit; 0 otherwise),
  - `is_new_file(tool_name, tool_input) -> bool` (Write to a path),
  - `offloaded_since(ts, *, call_log_path) -> bool` (any call-log entry with
    `ts ≥ turn_started_ts`),
  - `evaluate(event, *, deps) -> dict|None` — returns the PreToolUse allow
    response, logging `missed_offload` + attaching a soft warning when the
    heuristic trips; `None`/allow otherwise. Never raises, never denies.
  - `LARGE_CHARS = 1200` (tunable constant).
- `mlx_mcp_server/hook/gate_main.py` (or `gate.py:main`) — stdin/stdout entry,
  console script `mlx-offload-gate`. Always exit 0.
- `mlx_mcp_server/hook/__main__.py` (existing) — add the turn-state stamp + the
  nudge line to the `UserPromptSubmit` path.
- `mlx_mcp_server/hook/logs.py` (existing) — add `missed_offload` to `DECISIONS`.
- `token-metrics/tools/exporter.py` — ensure `missed_offload` flows through the
  existing `mlx_hook_decision_total` gauge (it already reads all decisions; just
  confirm no allowlist filtering).
- `token-metrics/dashboard/build_dashboard.py` + regenerated JSON — add the two
  panels under the "Offload Capture" row.

Each unit takes injectable deps (clock, paths, a chat-less heuristic) so it is
unit-testable without live oMLX or a live transcript.

## Error handling principles

- Both hooks **never raise** and **never block** a tool call (the gate always
  returns allow). Any unexpected error → silent allow.
- All file reads are best-effort; a missing/garbled `turn-state.json` means "no
  known turn start" → the gate treats offload-state as unknown and stays silent
  (fail open, no false nag).
- Timeouts bounded; the gate does no network calls at all.

## Data / privacy

- `missed_offload` log line carries counts/labels only:
  `{ts, decision:"missed_offload", category, confidence:0.0}` — `category` is a
  coarse label derived from file extension (e.g. `code`, `docs`, `other`), never
  the path or content.
- `turn-state.json` holds only a timestamp. No prompt/response/code text anywhere.

## Testing

- turnstate: stamp then read returns it; missing file → `None`; garbage → `None`.
- gate.written_size: Write/Edit/MultiEdit shapes; unknown tool → 0.
- gate.offloaded_since: entry after ts → True; only-before → False; missing log
  → False.
- gate.evaluate: large + none-offloaded → logs `missed_offload` + allow+warning;
  small write → silent allow; offloaded-this-turn → silent allow; unknown turn
  start → silent allow; never returns deny; never raises on malformed event.
- UserPromptSubmit nudge: stamps turn-state; injects the counts line; still
  performs the existing offload behavior.
- exporter/dashboard: `missed_offload` appears in the gauge; panels build from a
  fixture.

## Success criteria

- The dashboard shows a **"Local generation share"** that we can watch climb as
  the assistant routes generation to local — and a **"Missed offloads"** count we
  want trending toward zero.
- The gate never blocks or breaks a tool call; warnings are soft and logged.
- Combined with the discipline (assistant actually offloading), realized savings
  rise materially beyond the prompt-only slice.
