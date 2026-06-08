import time
from dataclasses import dataclass

import httpx

from .config import Config


@dataclass
class ChatResponse:
    content: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    elapsed_seconds: float


@dataclass
class ModelInfo:
    id: str


class LLMClient:
    def __init__(self, config: Config) -> None:
        self.config = config
        headers: dict[str, str] = {}
        if config.api_key:
            headers["Authorization"] = f"Bearer {config.api_key}"
        self._http = httpx.AsyncClient(
            base_url=config.base_url,
            headers=headers,
            timeout=config.timeout,
        )

    async def chat(
        self,
        message: str,
        system_prompt: str = "",
        temperature: float = 0.7,
        max_tokens: int = 512,
        top_p: float = 1.0,
        top_k: int = 0,
    ) -> ChatResponse:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": message})

        payload: dict = {
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "top_p": top_p,
        }
        if top_k > 0:
            payload["top_k"] = top_k
        if self.config.default_model:
            payload["model"] = self.config.default_model

        start = time.monotonic()
        resp = await self._http.post("/v1/chat/completions", json=payload)
        resp.raise_for_status()
        elapsed = time.monotonic() - start

        data = resp.json()
        usage = data.get("usage", {})
        return ChatResponse(
            content=data["choices"][0]["message"]["content"],
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
            elapsed_seconds=elapsed,
        )

    async def list_models(self) -> list[ModelInfo]:
        resp = await self._http.get("/v1/models")
        resp.raise_for_status()
        return [ModelInfo(id=m["id"]) for m in resp.json().get("data", [])]

    async def health_check(self) -> dict:
        # Try /health first — works without auth on oMLX and other backends
        try:
            resp = await self._http.get("/health", timeout=5.0)
            if resp.status_code == 200:
                data = resp.json()
                result: dict = {"status": "ok", "url": self.config.base_url}
                if "engine_pool" in data:
                    pool = data["engine_pool"]
                    result["models_loaded"] = f"{pool.get('loaded_count', 0)}/{pool.get('model_count', 0)}"
                return result
        except httpx.ConnectError:
            return {
                "status": "unreachable",
                "url": self.config.base_url,
                "hint": f"Make sure your LLM backend is running at {self.config.base_url}.",
            }
        except Exception:
            pass  # /health not available on this backend, fall through

        # Fall back to /v1/models (MLX LM, Ollama, LM Studio)
        try:
            resp = await self._http.get("/v1/models", timeout=5.0)
            resp.raise_for_status()
            models = [m["id"] for m in resp.json().get("data", [])]
            return {"status": "ok", "url": self.config.base_url, "models": models}
        except httpx.ConnectError:
            return {
                "status": "unreachable",
                "url": self.config.base_url,
                "hint": f"Make sure your LLM backend is running at {self.config.base_url}.",
            }
        except Exception as exc:
            return {
                "status": "error",
                "url": self.config.base_url,
                "error": str(exc),
                "hint": "Check that your backend is running and accessible.",
            }

    async def aclose(self) -> None:
        await self._http.aclose()
