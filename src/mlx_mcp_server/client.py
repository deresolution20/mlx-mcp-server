import re
import time
from dataclasses import dataclass

import httpx

from .config import Config
from .runtime_config import read_runtime_model, write_runtime_model


@dataclass
class ChatResponse:
    content: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    elapsed_seconds: float
    model: str = ""


@dataclass
class ModelInfo:
    id: str


class LLMClient:
    def __init__(self, config: Config) -> None:
        self.config = config
        # Runtime override: set_model() writes here + to disk; loaded from disk at startup.
        # Priority: _runtime_model > config.default_model (env) > auto-detect.
        self._runtime_model: str = read_runtime_model()
        self._resolved_model: str | None = None  # cached auto-detect result
        self._model_resolved: bool = False
        headers: dict[str, str] = {}
        if config.api_key:
            headers["Authorization"] = f"Bearer {config.api_key}"
        self._http = httpx.AsyncClient(
            base_url=config.base_url,
            headers=headers,
            timeout=config.timeout,
            trust_env=False,  # don't inherit HTTP_PROXY from environment (avoids leaking api_key to proxy)
        )

    def set_model(self, model: str) -> None:
        """Switch the active model at runtime. Persists to disk across restarts.

        Pass '' to clear the override and fall back to env var / auto-detect.
        """
        self._runtime_model = model
        # Reset auto-detect cache so a subsequent clear() re-queries the backend.
        self._resolved_model = None
        self._model_resolved = False
        write_runtime_model(model)

    def get_active_model(self) -> str:
        """Return the currently configured model name (not async — sync inspection only)."""
        return self._runtime_model or self.config.default_model or "(auto-detect)"

    async def _get_model(self) -> str:
        """Priority: runtime override → env var → cached auto-detect → live /v1/models."""
        if self._runtime_model:
            return self._runtime_model
        if self.config.default_model:
            return self.config.default_model
        if not self._model_resolved:
            try:
                models = await self.list_models()
                self._resolved_model = models[0].id if models else None
            except Exception:
                self._resolved_model = None  # backend unreachable or doesn't support listing
            self._model_resolved = True
        return self._resolved_model or ""

    @staticmethod
    def _strip_thinking(text: str) -> str:
        """Remove thinking preamble from Qwen3 responses.

        Handles two formats:
        1. <think>...</think> tags — standard Qwen3 API output
        2. "Thinking Process:\\n\\n1. ..." plain text — oMLX strips the tags but
           leaves the content, so we detect and remove the content block directly.
        """
        # Format 1: standard <think> XML tags
        text = re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL)

        # Format 2: oMLX strips the tags but leaves "Thinking Process:\n\n1. ..." blocks.
        # The actual answer follows as the first non-numbered, non-bulleted paragraph.
        if re.match(r"\s*Thinking Process:", text):
            # Walk lines: skip everything until we hit a blank line followed by a
            # line that doesn't start with a digit, bullet, asterisk, or whitespace —
            # that's where the real answer begins.
            paragraphs = re.split(r"\n{2,}", text.strip())
            answer_parts = []
            in_thinking = True
            for para in paragraphs:
                if in_thinking:
                    # A paragraph is "thinking" if it starts with a heading, number,
                    # bullet, bold marker, or is the "Thinking Process:" header itself.
                    first_line = para.lstrip()
                    is_thinking_para = bool(re.match(
                        r"(Thinking Process:|^\d+[\.\)]|^[\*\-]|^\*\*|\bLet['']s adjust\b)",
                        first_line,
                        re.MULTILINE,
                    ))
                    if not is_thinking_para:
                        in_thinking = False
                        answer_parts.append(para)
                else:
                    answer_parts.append(para)
            text = "\n\n".join(answer_parts)

        return text.strip()

    async def chat(
        self,
        message: str,
        system_prompt: str = "",
        temperature: float = 0.7,
        max_tokens: int = 1024,
        top_p: float = 1.0,
        top_k: int = 0,
        enable_thinking: bool = False,
    ) -> ChatResponse:
        # Layer 3: inject /no_think token into the user message.
        # Qwen3's chat template checks for this token in the conversation text.
        # oMLX ignores enable_thinking in the payload, but this works at the token level.
        no_think_prefix = "/no_think\n" if not enable_thinking else ""

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": no_think_prefix + message})

        payload: dict = {
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "top_p": top_p,
            "enable_thinking": enable_thinking,  # Qwen3: suppresses chain-of-thought when False
        }
        if top_k > 0:
            payload["top_k"] = top_k

        model = await self._get_model()
        if model:
            payload["model"] = model

        start = time.monotonic()
        resp = await self._http.post("/v1/chat/completions", json=payload)
        resp.raise_for_status()
        elapsed = time.monotonic() - start

        data = resp.json()
        usage = data.get("usage", {})
        content = data["choices"][0]["message"]["content"]
        if not enable_thinking:
            content = self._strip_thinking(content)
        return ChatResponse(
            content=content,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
            elapsed_seconds=elapsed,
            model=data.get("model") or model,  # oMLX may return "" — fall back to resolved model
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
