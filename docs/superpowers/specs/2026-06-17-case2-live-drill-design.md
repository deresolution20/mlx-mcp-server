# Case-2 Live Drill — Design

**Date:** 2026-06-17
**Status:** Approved (design); pending implementation plan
**Repo:** `mlx-mcp-server`

## Problem

The offload enforcement hook (v0.3.0, live) has two failure paths. **Case 1**
(quality gate-fail → silent escalation to Claude) fires routinely and is proven
in production. **Case 2** (oMLX *infrastructure* error → run `omlx restart`,
poll `/health`, inject a loud PAUSE directive, log `infra_error`) is fully
unit-tested in `hook/restart.py` and `hook/run.py::_case2`, but has **never
fired against a real down server.** We have not seen the actual `omlx restart`
command run from inside the hook, nor confirmed the real recovery + directive
end-to-end.

We need to fire that path once, for real, **without** leaving Brice's working
oMLX server down or letting Claude silently burn Opus tokens.

## Goal

A one-shot, on-demand drill that forces a genuine oMLX outage, drives the **live**
`mlx-offload-hook` against it, and asserts the full real Case-2 path:

- the hook detects the transport error,
- runs the **actual** `omlx restart`,
- recovers the server,
- injects the PAUSE directive Claude would see,
- logs exactly one `infra_error` decision (counts/labels only),

then leaves oMLX **healthy** — with a hard backstop if recovery fails.

## Scope

**In scope:**
- A pure-stdlib, dependency-injected drill module `mlx_mcp_server/hook/drill.py`.
- A console script `mlx-case2-drill` (entry point in `pyproject.toml`).
- Unit tests with mocked subprocess / health / hook-invocation (no live oMLX).
- A README note: what the drill does, when to run it (idle only), how to read
  PASS/FAIL.

**Out of scope:**
- Auto-wiring or scheduling the drill (run manually, on demand).
- A Case-1 drill (already proven in production).
- Any new oMLX-talking code — reuse `hook/omlx.py::resolve_omlx` and the existing
  health helper.
- Driving the drill through a live Claude turn (it pipes stdin to the hook script
  directly — deterministic and zero Claude tokens).

## Approach

**Real outage, self-healing** (chosen over a simulated dry-run for fidelity).
The drill stops the real server, fires a crafted prompt at the live console
script, and lets the hook's own real `omlx restart` recover it. Faithfulness is
the whole point — a simulated transport error would not exercise the actual
restart command, which is the one piece never run live.

The drill drives the hook by **piping a fixed stdin JSON** into the installed
`mlx-offload-hook` executable and capturing stdout + exit code — not by issuing a
live Claude prompt. This is deterministic, capturable, and spends no Claude
tokens on the drill itself.

The crafted prompt is a fixed, clearly-offloadable, **>40-char** summarize-style
string so it clears the prefilter and reaches the first network call (classify).
With oMLX down, that call raises `OmlxTransportError` → Case 2. (The prompt text
need not be "good" — it only needs to survive the prefilter; the outage triggers
at the first HTTP call regardless of category.)

## Architecture / Sequence

```
mlx-case2-drill
  ├─ 1. PRE-CHECK: /health must be UP
  │        └─ already down? -> abort loudly (don't mask a real outage) [exit 2]
  ├─ 2. ARM finally/trap: guarantees a recovery attempt even on mid-script death
  ├─ 3. omlx stop -> confirm /health now FAILS
  ├─ 4. echo {fixed offloadable prompt JSON} | mlx-offload-hook
  │        capture stdout + exit code
  ├─ 5. ASSERT real Case-2 fired:
  │        a. hook exit 0 (never hard-blocks)
  │        b. stdout additionalContext contains PAUSE directive
  │           ("Do NOT silently proceed on Opus" / "PAUSE")
  │        c. ~/.omlx/hook-decisions.jsonl gained exactly ONE infra_error line
  │           (and that line carries NO prompt/response text — privacy check)
  │        d. /health is UP again (hook's own omlx restart recovered it)
  ├─ 6. BACKSTOP: if 5d false -> drill runs `omlx start` itself,
  │        report FAIL, exit non-zero (never leave a dead server)
  └─ 7. REPORT: PASS/FAIL + captured directive + per-step timings
```

## Components (units)

- `hook/drill.py` — orchestrator. Injectable deps so it is unit-testable without
  a live oMLX:
  - `health_fn() -> bool` (default: reuse the hook's `/health` check),
  - `run_fn(args) -> CompletedProcess` (default `subprocess.run`, for
    `omlx stop` / `omlx start`),
  - `hook_fn(stdin_json) -> (stdout, exit_code)` (default: pipe to the
    `mlx-offload-hook` executable),
  - `decisions_path` (default `~/.omlx/hook-decisions.jsonl`),
  - returns a `DrillResult(passed, steps, captured_directive, detail)`.
- `hook/__main__`-style entry `drill:main()` — wires real defaults, prints the
  report, sets exit code (0 = PASS, non-zero = FAIL/abort).
- `pyproject.toml` — add `mlx-case2-drill = "mlx_mcp_server.hook.drill:main"` to
  `[project.scripts]`; bump version.
- `README.md` — "Case-2 live drill" subsection under the hook docs.

## Error handling principles

- The drill **never raises uncaught** — all work inside try/finally; the finally
  block always attempts to confirm/restore oMLX health.
- A failed pre-check (server already down) is an **abort**, not a FAIL — it would
  mask a real outage the drill didn't cause.
- If the hook's restart did not recover the server, the drill's own `omlx start`
  backstop runs before reporting, and the run is FAIL with non-zero exit.
- The `infra_error` log assertion doubles as a **privacy regression check**: the
  appended line must contain only the allowed counts/labels keys, never text.

## Testing

Pure-stdlib, DI'd → unit tests with mocked `run_fn`, `health_fn`, `hook_fn`
(mirrors `test_restart.py`):
- **pre-check abort:** health_fn returns down → abort, exit 2, no `omlx stop` issued.
- **happy path:** down→fire→recover; hook_fn returns PAUSE stdout + exit 0,
  decisions file gains one `infra_error` → `passed=True`.
- **recovery backstop:** post-hook health still down → drill issues `omlx start`,
  `passed=False`, non-zero exit.
- **privacy check:** a decisions line containing a text field fails the assertion.

No live oMLX in the suite; the real outage happens only when Brice runs the
console script by hand.

## Privacy

The drill reads only counts/labels from `hook-decisions.jsonl` and asserts no
text fields are present. It writes nothing sensitive. Runs entirely on-machine.

## Success criteria

- Running `mlx-case2-drill` on an idle, healthy machine prints **PASS** with the
  captured PAUSE directive, and oMLX is healthy afterward.
- The drill proves the real `omlx restart` recovers the server from inside the
  hook — the one thing never exercised live.
- A broken recovery surfaces as **FAIL** with a non-zero exit and an `omlx start`
  backstop — never a silently-dead server.
