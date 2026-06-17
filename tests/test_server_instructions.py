from mlx_mcp_server import server


def test_instructions_constant_names_behavior_tool_and_category():
    low = server._SERVER_INSTRUCTIONS.lower()
    # Names the behavior, the tool, and the category convention.
    assert "offload" in low
    assert "iterate" in low
    assert "category" in low


def test_instructions_mention_what_stays_on_claude():
    low = server._SERVER_INSTRUCTIONS.lower()
    assert "multi-file" in low or "judgment" in low


def test_instructions_are_wired_into_fastmcp():
    # FastMCP exposes the instructions it was constructed with.
    assert getattr(server.mcp, "instructions", None) == server._SERVER_INSTRUCTIONS
