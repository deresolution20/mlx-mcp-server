#!/usr/bin/env bash
# Claude Code PreToolUse hook (matcher: Task) — nudge before subagent dispatch.
# Non-blocking: prints context to stdout and exits 0.
cat <<'EOF'
[offload-first] About to delegate to a subagent — if this chunk is summarize /
boilerplate / single-file-review / extract / explain, run it through the mlx
`iterate` tool first instead of spending Claude tokens.
EOF
exit 0
