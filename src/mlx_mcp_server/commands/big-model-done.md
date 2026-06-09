Exit Big Model Mode: switch back to the fast 4-bit model and reopen all closed apps.

Steps:
1. Call the `set_model` MCP tool (mlx server) with model_name="Qwen2.5-Coder-32B-Instruct-4bit"
2. Run the restore script: `bash ~/bin/mlx-big-model-restore.sh`
3. Display this exact summary block:

```
⚡ Normal Mode restored
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ Model:  Qwen2.5-Coder-32B-Instruct-4bit (~19 tok/s)
🔄 Apps:   Relaunching — Chrome restores all tabs automatically
```

No extra commentary.
