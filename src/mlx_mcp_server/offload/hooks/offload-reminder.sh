#!/usr/bin/env bash
# Claude Code UserPromptSubmit hook — injects the offload-first reminder.
# Non-blocking: prints context to stdout and exits 0.
cat <<'EOF'
[offload-first] Before doing summarize / boilerplate / single-file-review /
extract / explain work yourself — or delegating it to a subagent — route it
through the mlx `iterate` tool first (local model, free, private). Pass a gate so
it can self-correct, and tag a `category`. Keep multi-file reasoning, judgment
calls, tool-using work, and the live reply on Claude.
EOF
exit 0
