# Post-mortem: the token-savings experiment didn't pan out

**Date:** 2026-06-17
**Verdict:** The offload layer did not save meaningful money. We stripped it
out and kept the small, honest tool underneath.

## What this was supposed to be

A small MCP server so Claude Code could call **local MLX models** (free,
on-machine, private) and offload cheap grunt work off the paid Claude API —
saving tokens. That's a good, tight idea. The MCP server part works.

## What it became

Chasing "save more," we bolted on a whole factory:

- A `UserPromptSubmit` **offload hook** that classified prompts and injected
  local drafts.
- A `PreToolUse` **gate** that nagged when a big write happened with nothing
  offloaded.
- An **eval suite** (48 gated cases) + runner to measure local-model quality.
- A **dashboard** with cache-vs-generation panels and Opus/Sonnet/Haiku
  tier-pricing what-ifs.
- An **installer** that wired all the hooks into `~/.claude/settings.json`.
- A flip of the global Claude default model to Sonnet.

None of that was the original tool. Most of it was machinery to *prove* the
tool was working — and the proof came back negative.

## Why it didn't save money (the honest numbers)

Measured from the token collector's own cumulative state on 2026-06-17, priced
at Opus rates. Total bill ≈ **$950**, broken down by token *kind*:

| Kind | Tokens | Cost | Share |
|---|---|---|---|
| cache_read | 1.005 B | $502.65 | 53% |
| cache_creation | 42.4 M | $265.17 | 28% |
| **output (generation)** | **7.1 M** | **$177.55** | **19%** |
| input | 1.0 M | $5.07 | 0.5% |

**81% of the bill is cache** — long Claude Code sessions re-reading large
context every turn. The offload layer can only ever touch the **generation
output** slice (19%). So its hard ceiling is ~$177, and what it actually
realized was **~$1.25** — an offload share of **0.017%**. We were optimizing
the smallest slice of the bill with the most machinery.

## The thing that actually saved money isn't this tool

The one lever that moved real dollars was switching the default model from
Opus to Sonnet: **same token volume, ~40% cheaper (~$380)**; Haiku would be
~80% (~$760). That's a one-line `settings.json` change. It has **nothing to do
with this MCP server.** Dressing a config toggle up as product work was the
core self-deception here.

(The Sonnet default is left in place — it's a legitimate, independent cost
choice. Keep it or revert it; it lives in `~/.claude/settings.json`, not here.)

## What we kept

The small tool that was the point all along — an MCP server exposing local
models to Claude Code. Seven tools, ~1,420 LOC, 125 tests passing:

- `chat`, `iterate` (local-first with a self-correcting gate + escalation),
  `quick_test`, `set_model`, `set_work_hours_guard`, `health_check`,
  `list_models`.

Call it what it is: a **convenience-and-privacy** tool for routing grunt work
to a free local model when *you* choose to. It is **not** a measurable
cost-saver, and the README/no longer claims to be one.

## What we removed

- `hook/` — the offload-enforcement layer (hook, gate, classifier, drill).
- `eval/` — the eval suite + runner.
- `offload/` — bundled hook scripts + `/offload` skill, and the installer code
  that wired them in.
- Console scripts `mlx-offload-hook`, `mlx-offload-gate`, `mlx-case2-drill`.
- The dead hook entries in `~/.claude/settings.json` (these referenced scripts
  that — after the strip — no longer exist; that was part of the "it still
  doesn't work" breakage).

Net: 44 files, ~2,255 lines deleted.

## Lessons

1. **Measure the whole bill before optimizing a slice.** Had we computed the
   cache-vs-output split on day one, we'd have known the ceiling was $177, not
   "save the API budget."
2. **Don't build machinery to justify an idea.** The eval suite and dashboard
   existed largely to make the offload look like it was working.
3. **The cheap lever beat the clever one 300×.** A model-tier toggle did more
   than the entire offload project. Reach for the boring config change first.
4. **Ship small. Name it honestly.** A free, private local-model bridge is a
   genuinely useful little tool. It just isn't a token-savings product, and
   pretending otherwise cost more effort than it ever saved.
