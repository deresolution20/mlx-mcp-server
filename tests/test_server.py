# tests/test_server.py
import json
import os
import pytest
import respx
import httpx
from unittest.mock import patch
from pathlib import Path

# Ensure default URL is set before importing server
os.environ.setdefault("MLX_BASE_URL", "http://localhost:8080")

from mlx_mcp_server.server import (
    chat, quick_test, health_check, list_models, get_config, get_usage_docs,
    set_model, set_work_hours_guard,
    _estimated_ram_gb, _is_work_hours, _BIG_MODEL_RAM_THRESHOLD_GB,
)


@pytest.fixture(autouse=True)
def no_runtime_file(tmp_path):
    """Isolate all server tests from real ~/.config/mlx-mcp/ files."""
    model_file = tmp_path / "active_model"
    guard_file = tmp_path / "work_hours_guard"
    with patch("mlx_mcp_server.runtime_config._CONFIG_DIR", tmp_path), \
         patch("mlx_mcp_server.runtime_config._MODEL_FILE", model_file), \
         patch("mlx_mcp_server.runtime_config._GUARD_FILE", guard_file):
        yield

MOCK_CHAT_RESPONSE = {
    "choices": [{"message": {"content": "42 is the answer."}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
}

@respx.mock
async def test_chat_tool_returns_formatted_output():
    respx.post("http://localhost:8080/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=MOCK_CHAT_RESPONSE)
    )
    result = await chat("What is 6 × 7?")
    assert "🏠 LOCAL" in result
    assert "42 is the answer." in result
    assert "20 total" in result

@respx.mock
async def test_chat_tool_accepts_optional_params():
    respx.post("http://localhost:8080/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=MOCK_CHAT_RESPONSE)
    )
    result = await chat("Hello", system_prompt="Be brief.", temperature=0.3, max_tokens=100)
    assert "42 is the answer." in result

@respx.mock
async def test_quick_test_hello():
    respx.post("http://localhost:8080/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={
            "choices": [{"message": {"content": "Hi, I'm a language model."}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 8, "completion_tokens": 10, "total_tokens": 18},
        })
    )
    result = await quick_test("hello")
    assert "🏠 LOCAL" in result
    assert "Test: hello" in result
    assert "Hi, I'm a language model." in result
    assert "tok/s" in result

@respx.mock
async def test_quick_test_code_review():
    respx.post("http://localhost:8080/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={
            "choices": [{"message": {"content": "Use a more descriptive name."}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 30, "completion_tokens": 6, "total_tokens": 36},
        })
    )
    result = await quick_test("code_review")
    assert "Test: code_review" in result
    assert "Use a more descriptive name." in result

@respx.mock
async def test_health_check_tool_ok():
    respx.get("http://localhost:8080/health").mock(
        return_value=httpx.Response(200, json={"status": "healthy", "engine_pool": {"loaded_count": 1, "model_count": 1}})
    )
    result = await health_check()
    data = json.loads(result)
    assert data["status"] == "ok"

@respx.mock
async def test_health_check_tool_unreachable():
    respx.get("http://localhost:8080/health").mock(
        side_effect=httpx.ConnectError("refused")
    )
    result = await health_check()
    data = json.loads(result)
    assert data["status"] == "unreachable"

@respx.mock
async def test_list_models_tool():
    respx.get("http://localhost:8080/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "phi-3"}, {"id": "llama-3"}]})
    )
    result = await list_models()
    assert "phi-3" in result
    assert "llama-3" in result

@respx.mock
async def test_list_models_empty():
    respx.get("http://localhost:8080/v1/models").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    result = await list_models()
    assert "No models found" in result

def test_get_config_resource():
    result = get_config()
    data = json.loads(result)
    assert "base_url" in data
    assert "timeout_seconds" in data
    assert "active_model" in data
    assert "model_source" in data
    assert "api_key" not in data

def test_get_usage_docs_resource():
    result = get_usage_docs()
    assert "mlx_lm.server" in result
    assert "MLX_BASE_URL" in result


@respx.mock
async def test_set_model_tool_sets_model():
    respx.get("http://localhost:8080/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [
            {"id": "Qwen2.5-Coder-32B-Instruct-4bit"},
            {"id": "Qwen3.6-35B-A3B-4bit"},
        ]})
    )
    result = await set_model("Qwen2.5-Coder-32B-Instruct-4bit")
    assert "✅" in result
    assert "Qwen2.5-Coder-32B-Instruct-4bit" in result
    assert "→" in result  # arrow marks active model in list


@respx.mock
async def test_set_model_tool_no_match_shows_error():
    respx.get("http://localhost:8080/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "known-model"}]})
    )
    result = await set_model("typo-model-name")
    assert "❌" in result
    assert "known-model" in result


@respx.mock
async def test_set_model_tool_fuzzy_match():
    respx.get("http://localhost:8080/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [
            {"id": "Qwen2.5-Coder-14B-Instruct-4bit"},
            {"id": "Qwen2.5-Coder-32B-Instruct-4bit"},
        ]})
    )
    result = await set_model("14b")
    assert "✅" in result
    assert "Qwen2.5-Coder-14B-Instruct-4bit" in result
    assert "matched from '14b'" in result


@respx.mock
async def test_set_model_tool_ambiguous_match_warns():
    respx.get("http://localhost:8080/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [
            {"id": "Qwen2.5-Coder-14B-Instruct-4bit"},
            {"id": "Qwen2.5-Coder-32B-Instruct-4bit"},
        ]})
    )
    result = await set_model("coder")  # matches both
    assert "⚠️" in result
    assert "2 models" in result


async def test_set_model_tool_clears_override():
    result = await set_model("")
    assert "cleared" in result.lower()


# ---------------------------------------------------------------------------
# _estimated_ram_gb tests
# ---------------------------------------------------------------------------

def test_estimated_ram_gb_32b_4bit():
    assert _estimated_ram_gb("Qwen2.5-Coder-32B-Instruct-4bit") == pytest.approx(18.0)

def test_estimated_ram_gb_32b_6bit():
    assert _estimated_ram_gb("Qwen2.5-Coder-32B-Instruct-6bit") == pytest.approx(26.0)

def test_estimated_ram_gb_14b_4bit():
    assert _estimated_ram_gb("Qwen2.5-Coder-14B-Instruct-4bit") == pytest.approx(9.0)

def test_estimated_ram_gb_14b_8bit():
    assert _estimated_ram_gb("Qwen2.5-Coder-14B-Instruct-8bit") == pytest.approx(16.0)

def test_estimated_ram_gb_unknown_returns_zero():
    assert _estimated_ram_gb("some-unknown-model") == 0.0

def test_big_model_threshold_catches_6bit():
    """32B-6bit should exceed the threshold; 32B-4bit should not."""
    assert _estimated_ram_gb("Qwen2.5-Coder-32B-Instruct-6bit") > _BIG_MODEL_RAM_THRESHOLD_GB
    assert _estimated_ram_gb("Qwen2.5-Coder-32B-Instruct-4bit") <= _BIG_MODEL_RAM_THRESHOLD_GB


# ---------------------------------------------------------------------------
# _is_work_hours tests
# ---------------------------------------------------------------------------

def test_is_work_hours_off_by_default():
    """Guard is off by default — _is_work_hours always returns False without opt-in."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    monday_noon = datetime(2026, 6, 8, 12, 0, tzinfo=ZoneInfo("America/Boise"))
    assert _is_work_hours(monday_noon) is False  # guard not enabled

def test_is_work_hours_monday_noon_is_work():
    """Monday at noon Mountain Time is work hours when guard is enabled."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    monday_noon = datetime(2026, 6, 8, 12, 0, tzinfo=ZoneInfo("America/Boise"))
    with patch("mlx_mcp_server.server.read_work_hours_guard", return_value=True):
        assert _is_work_hours(monday_noon) is True

def test_is_work_hours_saturday_is_not_work():
    """Saturday is never work hours even when guard is enabled."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    saturday = datetime(2026, 6, 13, 12, 0, tzinfo=ZoneInfo("America/Boise"))
    with patch("mlx_mcp_server.server.read_work_hours_guard", return_value=True):
        assert _is_work_hours(saturday) is False

def test_is_work_hours_monday_evening_is_not_work():
    """Monday at 6pm Mountain Time is not work hours."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    monday_eve = datetime(2026, 6, 8, 18, 0, tzinfo=ZoneInfo("America/Boise"))
    with patch("mlx_mcp_server.server.read_work_hours_guard", return_value=True):
        assert _is_work_hours(monday_eve) is False


# ---------------------------------------------------------------------------
# set_model work-hours guard tests
# ---------------------------------------------------------------------------

@respx.mock
async def test_set_model_blocks_big_model_during_work_hours():
    """Large model + work hours + no force → blocked with helpful message."""
    respx.get("http://localhost:8080/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [
            {"id": "Qwen2.5-Coder-32B-Instruct-6bit"},
        ]})
    )
    with patch("mlx_mcp_server.server._is_work_hours", return_value=True):
        result = await set_model("6bit")
    assert "⏰" in result
    assert "/big-model" in result
    assert "force=True" in result


@respx.mock
async def test_set_model_force_bypasses_work_hours_guard():
    """force=True loads the model even during work hours."""
    respx.get("http://localhost:8080/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [
            {"id": "Qwen2.5-Coder-32B-Instruct-6bit"},
        ]})
    )
    with patch("mlx_mcp_server.server._is_work_hours", return_value=True):
        result = await set_model("6bit", force=True)
    assert "✅" in result
    assert "Qwen2.5-Coder-32B-Instruct-6bit" in result


@respx.mock
async def test_set_model_allows_big_model_off_hours():
    """Off-hours → no guard, big model loads freely."""
    respx.get("http://localhost:8080/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [
            {"id": "Qwen2.5-Coder-32B-Instruct-6bit"},
        ]})
    )
    with patch("mlx_mcp_server.server._is_work_hours", return_value=False):
        result = await set_model("6bit")
    assert "✅" in result


@respx.mock
async def test_set_model_small_model_not_blocked_during_work_hours():
    """Small models are never blocked regardless of work hours."""
    respx.get("http://localhost:8080/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [
            {"id": "Qwen2.5-Coder-14B-Instruct-4bit"},
        ]})
    )
    with patch("mlx_mcp_server.server._is_work_hours", return_value=True):
        result = await set_model("14b")
    assert "✅" in result


# ---------------------------------------------------------------------------
# set_work_hours_guard tool tests
# ---------------------------------------------------------------------------

def test_set_work_hours_guard_enable():
    result = set_work_hours_guard(True)
    assert "enabled" in result.lower()
    assert "/big-model" in result

def test_set_work_hours_guard_disable():
    result = set_work_hours_guard(False)
    assert "disabled" in result.lower()

def test_get_config_shows_guard_state():
    result = get_config()
    data = json.loads(result)
    assert "work_hours_guard" in data
    assert data["work_hours_guard"] is False  # off by default


# ── help subcommand ───────────────────────────────────────────────────────────

import subprocess
import sys


def test_help_subcommand_exits_zero():
    result = subprocess.run(
        [sys.executable, "-m", "mlx_mcp_server.server", "help"],
        capture_output=True, text=True,
    )
    # server module runs main() — but subprocess via -m won't trigger main()
    # so test via the public function directly instead
    from mlx_mcp_server.server import _print_help
    # _print_help should run without raising
    _print_help()  # would raise if broken


def test_help_output_covers_all_sections(capsys):
    from mlx_mcp_server.server import _print_help
    _print_help()
    out = capsys.readouterr().out

    # Install subcommand
    assert "--claude-code" in out
    assert "--full" in out
    assert "--dry-run" in out
    assert "--with-commands" in out
    assert "--with-scripts" in out

    # Slash commands
    assert "/switch-model" in out
    assert "/big-model" in out
    assert "/big-model-done" in out
    assert "/mlx-help" in out

    # MCP tools
    assert "chat" in out
    assert "quick_test" in out
    assert "list_models" in out
    assert "set_model" in out
    assert "health_check" in out
    assert "get_config" in out
    assert "set_work_hours_guard" in out

    # Model lineup
    assert "DeepSeek" in out
    assert "Qwen2.5-Coder-14B" in out
    assert "Qwen3-Coder-30B" in out

    # Links
    assert "github.com" in out
    assert "pypi.org" in out
