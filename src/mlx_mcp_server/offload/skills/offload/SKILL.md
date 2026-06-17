---
name: offload
description: Use to route an eligible subtask (summarize, boilerplate, single-file review, extract, explain, simple refactor) to the local MLX model via the iterate tool before spending Claude tokens.
---

# Offload to the local model

Run eligible work on the local model first. The behavior also ships in the mlx
MCP server's own instructions; this skill is the low-friction manual path.

## When to use

Offload: summarize / extract / classify / reformat; boilerplate, test stubs,
docstrings, config; single-file or single-function review; simple refactors;
explaining code or errors; first drafts.

Keep on Claude: multi-file reasoning, architecture/judgment, tool-using work,
and the live reply.

## How

1. Pick a coarse `category`: review / boilerplate / summarize / extract /
   explain / other.
2. Choose a gate so the local model can self-correct:
   - Structural: `require_json`, `schema_keys`, `contains`, `regex`, `min_len`.
   - Executable: `check_command` — a shell command that reads the candidate at
     `$CANDIDATE_FILE` and exits 0 to pass (e.g. `pytest`, `ruff`, `tsc`).
   - No clean gate (fuzzy prose)? Skip the gate — `iterate` runs once and you
     verify the result yourself.
3. Call the tool:
   `mcp__mlx__iterate(message="<task>", category="<cat>", <gate args>)`
4. Read the footer:
   - "✅ Gate passed" → use the output.
   - "🔎 VERIFY ON CLAUDE" → no gate ran; check it before using.
   - "⚠️ ESCALATE TO CLAUDE" → local rungs exhausted; finish it yourself,
     re-delegate with sharper criteria, or pass a `big_model` to add a rung.

## Example

```
mcp__mlx__iterate(
  message="Write a Python function slugify(s) -> str: lowercase, spaces to hyphens, strip non-alphanumerics.",
  category="boilerplate",
  check_command="python - <<'PY'\nimport ast,os\nast.parse(open(os.environ['CANDIDATE_FILE']).read())\nPY",
)
```
