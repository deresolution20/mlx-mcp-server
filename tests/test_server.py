# tests/test_server.py
import json
import os
import pytest
import respx
import httpx

# Ensure default URL is set before importing server
os.environ.setdefault("MLX_BASE_URL", "http://localhost:8080")

from mlx_mcp_server.server import chat, quick_test, health_check, list_models, get_config, get_usage_docs

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
    assert "api_key" not in data

def test_get_usage_docs_resource():
    result = get_usage_docs()
    assert "mlx_lm.server" in result
    assert "MLX_BASE_URL" in result
