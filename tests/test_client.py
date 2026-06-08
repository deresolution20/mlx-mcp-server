# tests/test_client.py
import pytest
import respx
import httpx
from mlx_mcp_server.client import LLMClient, ChatResponse, ModelInfo
from mlx_mcp_server.config import Config

@pytest.fixture
def config():
    return Config(base_url="http://localhost:8080", default_model="", api_key="", timeout=5)

@pytest.fixture
def client(config):
    return LLMClient(config)

@respx.mock
async def test_chat_returns_response(client):
    respx.post("http://localhost:8080/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={
            "choices": [{"message": {"content": "Hello there!"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        })
    )
    result = await client.chat("Hi")
    assert isinstance(result, ChatResponse)
    assert result.content == "Hello there!"
    assert result.prompt_tokens == 10
    assert result.completion_tokens == 5
    assert result.total_tokens == 15
    assert result.elapsed_seconds >= 0

@respx.mock
async def test_chat_sends_system_prompt(client):
    route = respx.post("http://localhost:8080/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={
            "choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 1, "total_tokens": 21},
        })
    )
    await client.chat("Hello", system_prompt="You are a helpful assistant.")
    sent = route.calls[0].request
    import json
    body = json.loads(sent.content)
    assert body["messages"][0] == {"role": "system", "content": "You are a helpful assistant."}
    assert body["messages"][1] == {"role": "user", "content": "Hello"}

@respx.mock
async def test_chat_omits_empty_system_prompt(client):
    route = respx.post("http://localhost:8080/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={
            "choices": [{"message": {"content": "Hi"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
        })
    )
    await client.chat("Hello", system_prompt="")
    sent = route.calls[0].request
    import json
    body = json.loads(sent.content)
    assert len(body["messages"]) == 1
    assert body["messages"][0]["role"] == "user"

@respx.mock
async def test_chat_includes_model_when_set():
    config = Config(base_url="http://localhost:8080", default_model="mistral", api_key="", timeout=5)
    client = LLMClient(config)
    route = respx.post("http://localhost:8080/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={
            "choices": [{"message": {"content": "Hi"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
        })
    )
    await client.chat("Hello")
    import json
    body = json.loads(route.calls[0].request.content)
    assert body["model"] == "mistral"

@respx.mock
async def test_chat_raises_on_http_error(client):
    respx.post("http://localhost:8080/v1/chat/completions").mock(
        return_value=httpx.Response(500, text="Internal Server Error")
    )
    with pytest.raises(httpx.HTTPStatusError):
        await client.chat("Hi")

@respx.mock
async def test_list_models_returns_model_list(client):
    respx.get("http://localhost:8080/v1/models").mock(
        return_value=httpx.Response(200, json={
            "data": [{"id": "mistral-7b"}, {"id": "phi-3-mini"}]
        })
    )
    models = await client.list_models()
    assert len(models) == 2
    assert isinstance(models[0], ModelInfo)
    assert models[0].id == "mistral-7b"
    assert models[1].id == "phi-3-mini"

@respx.mock
async def test_list_models_empty(client):
    respx.get("http://localhost:8080/v1/models").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    models = await client.list_models()
    assert models == []

@respx.mock
async def test_health_check_ok(client):
    respx.get("http://localhost:8080/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "mistral-7b"}]})
    )
    result = await client.health_check()
    assert result["status"] == "ok"
    assert result["url"] == "http://localhost:8080"
    assert "mistral-7b" in result["models"]

@respx.mock
async def test_health_check_unreachable(client):
    respx.get("http://localhost:8080/v1/models").mock(
        side_effect=httpx.ConnectError("Connection refused")
    )
    result = await client.health_check()
    assert result["status"] == "unreachable"
    assert "hint" in result
    assert "mlx_lm.server" in result["hint"]
