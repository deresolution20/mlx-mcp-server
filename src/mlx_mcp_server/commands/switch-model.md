Call the `list_models` MCP tool (mlx server) and display the results as a numbered menu — each model on its own line with its number, name, and description.

Then ask the user: "Which model? Enter a number or name fragment."

Wait for their response. When they pick:
1. Call `set_model` with their choice (number → resolve to model name from the list; fragment → pass as-is and let the tool do fuzzy matching).
2. Call `quick_test` with test_type="code_review".
3. Parse the quick_test output and display a clean summary:

```
✅ Now running: <model name>
📊 Speed: <tok/s> tok/s  |  <tokens> tokens  |  <time>s
🎯 Best for: <one-liner description from list_models>

Test output:
<the actual model response from quick_test>
```

Keep the tone brief and factual. No extra commentary beyond the summary block.
