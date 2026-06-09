Show a reference card for all mlx-mcp-server slash commands and MCP tools.

Call the `get_config` MCP tool (mlx server) to get the current model and settings, then display this exact reference card, filling in the live values where marked:

```
mlx-mcp-server — local LLM bridge
══════════════════════════════════════════════════════

CURRENT STATUS
  Model:       <active model from get_config>
  oMLX URL:    <base_url from get_config>
  Work guard:  <work_hours_guard from get_config — "on (8am–5pm MT)" or "off">

──────────────────────────────────────────────────────

SLASH COMMANDS
  /switch-model      List models and switch interactively
  /big-model         Free RAM, load 6-bit 32B for max quality
  /big-model-done    Switch back to 4-bit, reopen all apps
  /mlx-help          Show this reference card

──────────────────────────────────────────────────────

MCP TOOLS
  chat(message, system_prompt?)
    → Send a prompt to the local LLM
    → Example: chat(message="explain this function")

  quick_test(test_type?)
    → Verify the active model responds correctly
    → test_type: hello | code_review | math  (default: hello)

  list_models()
    → List all available models with speed and description

  set_model(model_name, force?)
    → Switch active model by name or fragment
    → Example: set_model(model_name="14b")
    → force=True bypasses the work-hours guard

  health_check()
    → Confirm oMLX is reachable

  get_config()
    → Show current URL, model, and work-hours guard state

  set_work_hours_guard(enabled)
    → Toggle work-hours guard (blocks big models 8am–5pm MT on weekdays)
    → Example: set_work_hours_guard(enabled=True)

──────────────────────────────────────────────────────

MODEL LINEUP
  ⚡ DeepSeek-Coder-V2-Lite   ~135 tok/s  turbo — quick lookups & boilerplate
  ⚡ Qwen2.5-Coder-7B         ~80 tok/s   fast — solid everyday quality
  ⚖️  Qwen2.5-Coder-14B        ~28 tok/s   default — reliable for most tasks
  🧠 Qwen2.5-Coder-32B        ~19 tok/s   quality — complex & multi-file
  🔮 gemma-3-27b-it-qat       ~35 tok/s   best quality — use off-hours or /big-model

  Tip: /big-model frees ~8 GB of RAM to safely run the 6-bit 32B (~25 GB).
══════════════════════════════════════════════════════
```

No extra commentary. Just the card.
