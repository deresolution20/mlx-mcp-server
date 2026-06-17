from mlx_mcp_server.hook.prefilter import is_trivial


def test_short_prompt_is_trivial():
    assert is_trivial("ok") is True
    assert is_trivial("   ") is True


def test_control_word_is_trivial_even_if_longer_form():
    assert is_trivial("yes") is True
    assert is_trivial("Continue") is True
    assert is_trivial("thanks!") is True


def test_substantive_prompt_is_not_trivial():
    assert is_trivial("Summarize the following error log and tell me the root cause") is False
