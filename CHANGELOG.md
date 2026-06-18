# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.6.0] — Strip back to the core (the savings experiment is over)

The token-savings layer was measured and didn't pay off (offload ceiling ~$177,
realized ~$1.25, because 81% of the bill is cache, not generation). Removed the
machinery; kept the small, honest local-model bridge. See `POSTMORTEM.md`.

### Removed
- `hook/` — the offload-enforcement layer (`UserPromptSubmit` hook, classifier,
  generator, prefilter, turnstate, oMLX restart/recovery, Case-2 drill).
- `eval/` — the gated eval suite + runner.
- `offload/` — bundled hook scripts + `/offload` skill, and the installer code
  (`install_offload_layer`) that wired them into `~/.claude/settings.json`.
- Console scripts: `mlx-offload-hook`, `mlx-offload-gate`, `mlx-case2-drill`
  (only `mlx-mcp-server` remains).
- `--with-offload` / `--full` install flags.
- Net: 44 files / ~2,255 lines deleted; core 2,552 → 1,422 LOC.

### Kept
- MCP server + 7 tools: `chat`, `iterate` (local-first ladder with self-correcting
  gates), `quick_test`, `set_model`, `set_work_hours_guard`, `health_check`,
  `list_models`. 125 tests passing.

### Added
- `POSTMORTEM.md` — honest accounting of why the savings layer didn't work.
- README scope note reframing the project as a convenience/privacy tool, not a
  token-savings product.

## [0.5.1] — Docs + eval coverage (drafted on the local model)

### Added
- `CHANGELOG.md` (this file).
- Docstrings across the public surface: 61 function/class docstrings + 10 module-level docstrings (0 gaps remain).
- Eval suite doubled from 24 to 48 cases (8 per category across summarize, extract, explain, boilerplate, codegen, review).

### Fixed
- `iterate`'s `contains` gate now accepts a list of required substrings (previously a list was matched as one literal string, causing false escalations).

## [0.5.0] — Phase 2 internal tool-loop offload

### Added
- Phase 2 internal tool-loop offload: soft gate (`mlx-offload-gate`, PreToolUse on `Write|Edit|MultiEdit`) + turn-state tracking + end-of-turn nudge. Flags large generations written with nothing offloaded that turn; logs counts-only `missed_offload` and never blocks.
- Dashboard panels: "Local generation share" and "Missed offloads".
- Spec and plan docs for Phase 2.

## [0.4.0] — Case-2 live drill

### Added
- Case-2 live drill (`mlx-case2-drill` console script): forces a real oMLX outage, drives the live hook, and asserts detect → `omlx restart` → recover → inject PAUSE, with an `omlx start` backstop.
- Dependabot config.
- MIT license.
- Spec and plan docs for the drill.

### Changed
- Professionalized the README.

## [0.3.0] — Offload enforcement hook

### Added
- Offload enforcement hook on `UserPromptSubmit`: classifies prompts on the local model, offloads offloadable ones, and injects a local draft into context.
- Console-script entry point (`mlx-offload-hook`) + README wiring.
- Orchestrator with stdin/stdout entry point.
- oMLX restart + diagnose recovery (Case 2).
- Counts-only call and decision logs (never stores prompt/response text).
- Gated local generation with retry-then-escalate.
- Single-prompt local classifier and trivial-prompt prefilter.
- oMLX stdlib transport with a transport-error signal.

## [0.2.4] — Eval suite + iterate hardening

### Added
- Eval CLI (`python -m mlx_mcp_server.eval run`); results JSONL writer (counts-only) + summary aggregation; runner groups by model and is resilient to backend errors; curated gated suite across six categories; suite loader + gate-fn builder.
- `iterate` auto-escalates to a bigger local model before Claude; structural gate and executable (shell `check_command`) gate for the iterate loop.
- `--with-offload` CLI flag; `install_offload_layer` writes Tier 2 hooks + `/offload` skill idempotently; Tier 1 portable offload-first instructions on the MCP server.
- `iterate` MCP tool wiring gates + ladder to the client; local-first escalation ladder.
- Optional `category` arg + append-only call log for offload metrics.
- PyPI version badge.

### Changed
- Strip whole-response markdown fences before returning.

### Fixed
- `iterate` degrades to escalation on backend errors instead of crashing.
- Guard `os.makedirs` for bare-filename `--out` path.
- Drop redundant eval/suite force-include (duplicate wheel path).

### Removed
- Big Model Mode (dead feature; 30B-A3B is now the default).
