#!/bin/bash
# mlx-big-model-close.sh
# Closes memory-heavy apps to free RAM for the 6-bit LLM.
# oMLX and Claude Code stay running — they are the stack.
# Run via: bash ~/bin/mlx-big-model-close.sh

APPS=("Google Chrome" "Slack" "Obsidian" "Telegram" "Mail" "Calendar" "Claude")

echo "🧹 Big Model Mode — freeing RAM..."
echo ""

closed=()
for app in "${APPS[@]}"; do
    if osascript -e "tell application \"$app\" to quit" 2>/dev/null; then
        closed+=("$app")
        echo "  ✓ Closed $app"
    fi
done

if [ ${#closed[@]} -eq 0 ]; then
    echo "  (no target apps were running)"
fi

# Give macOS a moment to reclaim the freed pages
sleep 2

echo ""
echo "✅ Done. Load the 6-bit model in oMLX, then run /big-model in Claude Code."
echo "   When finished: bash ~/bin/mlx-big-model-restore.sh"
