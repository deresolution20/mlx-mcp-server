#!/bin/bash
# mlx-big-model-restore.sh
# Relaunches apps that were closed for Big Model Mode.
# Chrome will restore all tabs and windows automatically.
# Run via: bash ~/bin/mlx-big-model-restore.sh

APPS=("Google Chrome" "Slack" "Obsidian" "Telegram" "Mail" "Calendar" "Claude")

echo "🔄 Restoring apps..."
echo ""

for app in "${APPS[@]}"; do
    if open -a "$app" 2>/dev/null; then
        echo "  ✓ Launched $app"
    else
        echo "  ⚠  Could not launch $app (not installed?)"
    fi
done

echo ""
echo "✅ Apps relaunching. Chrome will restore all tabs automatically."
