Switch to Big Model Mode: close memory-heavy apps and load the 6-bit Qwen2.5-Coder-32B for maximum quality.

Steps:
1. Run the close script: `bash ~/bin/mlx-big-model-close.sh`
2. Call the `set_model` MCP tool (mlx server) with model_name="Qwen2.5-Coder-32B-Instruct-6bit" and force=True
3. Wait up to 30 seconds for oMLX to swap models — if quick_test fails with a connection error, wait 10s and retry once
4. Call `quick_test` with test_type="code_review" to confirm the model loaded
5. Display this exact summary block:

```
🧠 Big Model Mode active
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ Model:  Qwen2.5-Coder-32B-Instruct-6bit
📊 Speed:  <tok/s from quick_test> tok/s
🔒 Closed: Chrome · Slack · Obsidian · Telegram · Mail · Calendar · Claude Desktop

Run /big-model-done when finished to restore all apps.
```

Keep the output brief. No extra commentary.
