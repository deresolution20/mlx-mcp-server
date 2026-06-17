import io
import json
import urllib.error
import pytest
from mlx_mcp_server.hook import omlx


def _fake_opener(payload, status=200):
    def opener(req, timeout=None):
        if status >= 400:
            raise urllib.error.HTTPError(req.full_url, status, "err", {}, io.BytesIO(b""))
        class R:
            def read(self_): return json.dumps(payload).encode()
            def __enter__(self_): return self_
            def __exit__(self_, *a): return False
        return R()
    return opener


def test_chat_returns_content_and_token_counts():
    payload = {"choices": [{"message": {"content": "hello"}}],
               "usage": {"prompt_tokens": 11, "completion_tokens": 5}}
    res = omlx.chat("http://x", "k", "m", "sys", "usr", _opener=_fake_opener(payload))
    assert res.content == "hello"
    assert res.prompt_tokens == 11
    assert res.completion_tokens == 5


def test_chat_raises_transport_error_on_5xx():
    with pytest.raises(omlx.OmlxTransportError):
        omlx.chat("http://x", "k", "m", "s", "u", _opener=_fake_opener({}, status=503))


def test_chat_raises_transport_error_on_urlerror():
    def opener(req, timeout=None):
        raise urllib.error.URLError("connection refused")
    with pytest.raises(omlx.OmlxTransportError):
        omlx.chat("http://x", "k", "m", "s", "u", _opener=opener)
