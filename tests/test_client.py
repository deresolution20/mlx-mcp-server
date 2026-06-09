# tests/test_client.py
import pytest
import respx
import httpx
from unittest.mock import patch
from mlx_mcp_server.client import LLMClient, ChatResponse, ModelInfo
from mlx_mcp_server.config import Config


@pytest.fixture(autouse=True)
def no_runtime_file(tmp_path):
    """Isolate all client tests from the real ~/.config/mlx-mcp/active_model file."""
    model_file = tmp_path / "active_model"
    with patch("mlx_mcp_server.runtime_config._CONFIG_DIR", tmp_path), \
         patch("mlx_mcp_server.runtime_config._MODEL_FILE", model_file):
        yield


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
    # enable_thinking is not sent by default — omitting it avoids 400s on models
    # that don't recognise the field (e.g. Gemma 4)
    assert "enable_thinking" not in body

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
async def test_chat_auto_detects_model_when_not_configured(client):
    """When default_model is empty, client queries /v1/models and uses the first result."""
    respx.get("http://localhost:8080/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "auto-detected-model"}]})
    )
    respx.post("http://localhost:8080/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={
            "choices": [{"message": {"content": "Hi"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
            "model": "auto-detected-model",
        })
    )
    result = await client.chat("Hello")
    assert result.model == "auto-detected-model"


@respx.mock
async def test_chat_auto_detect_includes_model_in_payload(client):
    """Auto-detected model is sent in the request payload."""
    respx.get("http://localhost:8080/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "detected-model"}]})
    )
    chat_route = respx.post("http://localhost:8080/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={
            "choices": [{"message": {"content": "Hi"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
        })
    )
    await client.chat("Hello")
    import json as _json
    body = _json.loads(chat_route.calls[0].request.content)
    assert body["model"] == "detected-model"


@respx.mock
async def test_chat_caches_auto_detected_model(client):
    """/v1/models is only queried once — subsequent chat calls use the cached model."""
    models_route = respx.get("http://localhost:8080/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "cached-model"}]})
    )
    respx.post("http://localhost:8080/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={
            "choices": [{"message": {"content": "Hi"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
        })
    )
    await client.chat("First message")
    await client.chat("Second message")
    assert models_route.call_count == 1


@respx.mock
async def test_chat_graceful_when_model_detection_fails(client):
    """If /v1/models returns an error, chat proceeds without a model field."""
    respx.get("http://localhost:8080/v1/models").mock(
        return_value=httpx.Response(500, text="Server Error")
    )
    chat_route = respx.post("http://localhost:8080/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={
            "choices": [{"message": {"content": "Hi"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
        })
    )
    result = await client.chat("Hello")
    import json as _json
    body = _json.loads(chat_route.calls[0].request.content)
    assert "model" not in body
    assert result.content == "Hi"


def test_strip_thinking_removes_xml_tags():
    """Standard <think>...</think> tags are stripped (MLX-LM / direct API format)."""
    raw = "<think>\nLet me reason about this carefully.\n</think>\n\nThe answer is 42."
    assert LLMClient._strip_thinking(raw) == "The answer is 42."


def test_strip_thinking_removes_omlx_plain_text_format():
    """oMLX strips XML tags but leaves 'Thinking Process:' content — we strip that too."""
    raw = (
        "Thinking Process:\n\n"
        "1.  **Analyze**: The user asked a question.\n"
        "2.  **Consider**: I should answer directly.\n"
        "3.  **Draft**: \"The answer is 42.\"\n\n"
        "The answer is 42."
    )
    result = LLMClient._strip_thinking(raw)
    assert "Thinking Process:" not in result
    assert "The answer is 42." in result


def test_strip_thinking_passthrough_when_no_thinking():
    """Clean responses without thinking blocks are returned unchanged."""
    raw = "The answer is 42."
    assert LLMClient._strip_thinking(raw) == "The answer is 42."


def test_strip_thinking_handles_empty_string():
    assert LLMClient._strip_thinking("") == ""


@respx.mock
async def test_health_check_ok_via_health_endpoint(client):
    # /health works without auth (oMLX-style)
    respx.get("http://localhost:8080/health").mock(
        return_value=httpx.Response(200, json={"status": "healthy", "engine_pool": {"loaded_count": 1, "model_count": 2}})
    )
    result = await client.health_check()
    assert result["status"] == "ok"
    assert result["url"] == "http://localhost:8080"
    assert result["models_loaded"] == "1/2"

@respx.mock
async def test_health_check_ok_fallback_to_models(client):
    # /health not available, falls back to /v1/models
    respx.get("http://localhost:8080/health").mock(
        return_value=httpx.Response(404)
    )
    respx.get("http://localhost:8080/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "mistral-7b"}]})
    )
    result = await client.health_check()
    assert result["status"] == "ok"
    assert result["url"] == "http://localhost:8080"
    assert "mistral-7b" in result["models"]

@respx.mock
async def test_health_check_unreachable(client):
    respx.get("http://localhost:8080/health").mock(
        side_effect=httpx.ConnectError("Connection refused")
    )
    result = await client.health_check()
    assert result["status"] == "unreachable"
    assert "hint" in result


# ---------------------------------------------------------------------------
# set_model / runtime model switching tests
# ---------------------------------------------------------------------------

def test_set_model_updates_runtime_model(client):
    """set_model() updates the in-memory runtime model immediately."""
    assert client._runtime_model == ""
    client.set_model("Qwen2.5-Coder-32B-Instruct-4bit")
    assert client._runtime_model == "Qwen2.5-Coder-32B-Instruct-4bit"


def test_set_model_clears_auto_detect_cache(client):
    """set_model() resets the auto-detect cache so a fresh query runs next time."""
    client._resolved_model = "stale-model"
    client._model_resolved = True
    client.set_model("new-model")
    assert client._resolved_model is None
    assert client._model_resolved is False


def test_set_model_clear_resets_runtime(client):
    """set_model('') clears the runtime override."""
    client.set_model("some-model")
    client.set_model("")
    assert client._runtime_model == ""


@respx.mock
async def test_set_model_takes_priority_over_env_var():
    """Runtime model takes priority over MLX_DEFAULT_MODEL env var."""
    config = Config(base_url="http://localhost:8080", default_model="env-model", api_key="", timeout=5)
    client = LLMClient(config)
    client.set_model("runtime-model")

    chat_route = respx.post("http://localhost:8080/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={
            "choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6},
        })
    )
    await client.chat("hello")
    import json as _json
    body = _json.loads(chat_route.calls[0].request.content)
    assert body["model"] == "runtime-model"


@respx.mock
async def test_get_active_model_reflects_runtime(client):
    """get_active_model() returns the runtime model when set."""
    assert client.get_active_model() == "(auto-detect)"
    client.set_model("test-model")
    assert client.get_active_model() == "test-model"
    client.set_model("")
    assert client.get_active_model() == "(auto-detect)"
