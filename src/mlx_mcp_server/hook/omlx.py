"""Pure-stdlib transport to the local oMLX server for the offload hook.

A transport failure (unreachable / timeout / any non-2xx) is an INFRASTRUCTURE
problem (Case 2), distinct from a quality gate failure. It surfaces as
OmlxTransportError so the orchestrator can restart oMLX and pause — never a
silent fallback to Claude.
"""
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass


class OmlxTransportError(Exception):
    """oMLX unreachable / timeout / non-2xx — an infrastructure failure."""


@dataclass
class ChatResult:
    """A local chat call result or transport error."""
    content: str
    prompt_tokens: int
    completion_tokens: int


def resolve_omlx():
    """Return (base_url, api_key, model): Claude settings → env → defaults; model
    from the runtime override file, else the first model the server reports."""
    base = key = None
    try:
        with open(os.path.expanduser("~/.claude/settings.json")) as fh:
            env = json.load(fh).get("mcpServers", {}).get("mlx", {}).get("env", {})
        base, key = env.get("MLX_BASE_URL"), env.get("MLX_API_KEY")
    except (OSError, ValueError):
        pass
    base = base or os.environ.get("MLX_BASE_URL") or "http://localhost:8000"
    key = key or os.environ.get("MLX_API_KEY") or ""
    return base, key, _resolve_model(base, key)


def _resolve_model(base_url, api_key):
    """Pick a model id from the backend; empty string on failure."""
    try:
        m = open(os.path.expanduser("~/.config/mlx-mcp/active_model")).read().strip()
        if m:
            return m
    except OSError:
        pass
    try:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        req = urllib.request.Request(base_url.rstrip("/") + "/v1/models", headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        models = [m["id"] for m in data.get("data", [])]
        return models[0] if models else ""
    except (urllib.error.URLError, OSError, ValueError, KeyError):
        return ""


def chat(base_url, api_key, model, system, user, *, timeout=120,
         _opener=urllib.request.urlopen):
    """POST /v1/chat/completions and return a ChatResult.

    Raises OmlxTransportError on ANY transport failure (URLError, timeout, or
    non-2xx HTTP status) — these are Case-2 infrastructure errors.
    """
    body = {
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "temperature": 0.0, "max_tokens": 2048,
    }
    if model:
        body["model"] = model
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(base_url.rstrip("/") + "/v1/chat/completions",
                                 data=json.dumps(body).encode(), headers=headers,
                                 method="POST")
    try:
        with _opener(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
    except (urllib.error.HTTPError, urllib.error.URLError, OSError, ValueError) as e:
        raise OmlxTransportError(str(e)) from e
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise OmlxTransportError(f"malformed response: {e}") from e
    usage = data.get("usage") or {}
    return ChatResult(content,
                      int(usage.get("prompt_tokens", 0)),
                      int(usage.get("completion_tokens", 0)))
