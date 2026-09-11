"""Real providers.

Thin on purpose. Everything that makes the gateway worth having - routing, budgets,
fallback, caching, guardrails - lives above this layer and is tested without it. A
provider's only job is to turn a Request into text and a token count.

Prices are per 1000 tokens, (input, output), and are data rather than code so they can
be corrected without touching logic. They change; check them before quoting a figure.
"""

from __future__ import annotations

import os

import httpx

from ..types import Request, Usage
from .base import Provider, ProviderError, RateLimited


class OllamaProvider(Provider):
    """Local models. Free, so every price is zero and the budget only bounds the
    paid providers - which is the point of routing easy work here."""

    name = "ollama"

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        models: dict[str, tuple[float, float]] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.models = models or {
            "qwen2.5:3b-instruct": (0.0, 0.0),
            "qwen2.5:7b-instruct": (0.0, 0.0),
            "llama3.1:8b": (0.0, 0.0),
        }

    def complete(self, req: Request, model: str) -> tuple[str, Usage]:
        try:
            with httpx.Client(timeout=180.0) as client:
                r = client.post(
                    f"{self.base_url}/api/generate",
                    json={
                        "model": model,
                        "prompt": req.prompt,
                        "system": req.system,
                        "stream": False,
                        "options": {"num_predict": req.max_tokens, "temperature": 0.0},
                    },
                )
                r.raise_for_status()
                data = r.json()
        except httpx.HTTPError as exc:
            raise ProviderError(f"ollama: {exc}") from exc

        return data["response"].strip(), Usage(
            prompt_tokens=data.get("prompt_eval_count", 0),
            completion_tokens=data.get("eval_count", 0),
        )


class AnthropicProvider(Provider):
    name = "anthropic"

    def __init__(
        self, api_key: str | None = None, models: dict[str, tuple[float, float]] | None = None
    ) -> None:
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        self.models = models or {
            "claude-sonnet-5": (3.0, 15.0),
            "claude-haiku-4-5-20251001": (1.0, 5.0),
        }

    def complete(self, req: Request, model: str) -> tuple[str, Usage]:
        if not self.api_key:
            raise ProviderError("anthropic: ANTHROPIC_API_KEY is not set")
        try:
            from anthropic import Anthropic, RateLimitError
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise ProviderError("anthropic: SDK not installed") from exc

        try:
            msg = Anthropic(api_key=self.api_key).messages.create(
                model=model,
                max_tokens=req.max_tokens,
                temperature=0.0,
                system=req.system or "You are a helpful assistant.",
                messages=[{"role": "user", "content": req.prompt}],
            )
        except RateLimitError as exc:
            # Distinct from a generic failure: the right response is to fail over,
            # not to retry the same provider.
            raise RateLimited(f"anthropic: {exc}") from exc
        except Exception as exc:
            raise ProviderError(f"anthropic: {exc}") from exc

        return (
            "".join(b.text for b in msg.content if b.type == "text").strip(),
            Usage(prompt_tokens=msg.usage.input_tokens, completion_tokens=msg.usage.output_tokens),
        )


class HuggingFaceProvider(Provider):
    """Serverless inference through HF's OpenAI-compatible router."""

    name = "huggingface"

    def __init__(
        self,
        token: str | None = None,
        base_url: str = "https://router.huggingface.co/v1",
        models: dict[str, tuple[float, float]] | None = None,
    ) -> None:
        self.token = token or os.getenv("HF_TOKEN", "")
        self.base_url = base_url.rstrip("/")
        self.models = models or {"Qwen/Qwen2.5-7B-Instruct": (0.0, 0.0)}

    def complete(self, req: Request, model: str) -> tuple[str, Usage]:
        if not self.token:
            raise ProviderError("huggingface: HF_TOKEN is not set")
        messages = []
        if req.system:
            messages.append({"role": "system", "content": req.system})
        messages.append({"role": "user", "content": req.prompt})

        try:
            with httpx.Client(timeout=180.0) as client:
                r = client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.token}"},
                    json={
                        "model": model,
                        "messages": messages,
                        "max_tokens": req.max_tokens,
                        "temperature": 0.0,
                    },
                )
                if r.status_code == 429:
                    raise RateLimited("huggingface: rate limited")
                r.raise_for_status()
                data = r.json()
        except httpx.HTTPError as exc:
            raise ProviderError(f"huggingface: {exc}") from exc

        usage = data.get("usage", {})
        return data["choices"][0]["message"]["content"].strip(), Usage(
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
        )
