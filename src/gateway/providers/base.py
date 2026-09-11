"""Provider interface.

Cost is per-provider data rather than a global table, because prices differ per model
and change independently. A provider that cannot price itself cannot be budgeted, so
`price` is part of the interface rather than an optional extra.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..types import Request, Response, Usage


class ProviderError(RuntimeError):
    """Provider failed. Retryable by the fallback chain."""


class RateLimited(ProviderError):
    """Provider rejected us for rate reasons. Distinct, because the right response is
    to fail over rather than to retry the same provider."""


class Provider(ABC):
    name: str
    models: dict[str, tuple[float, float]]  # model -> (usd per 1k in, usd per 1k out)

    @abstractmethod
    def complete(self, req: Request, model: str) -> tuple[str, Usage]: ...

    def price(self, model: str, usage: Usage) -> float:
        rates = self.models.get(model)
        if rates is None:
            return 0.0
        return round(
            usage.prompt_tokens / 1000 * rates[0] + usage.completion_tokens / 1000 * rates[1],
            8,
        )

    def supports(self, model: str) -> bool:
        return model in self.models

    def make_response(self, req: Request, model: str, text: str, usage: Usage) -> Response:
        usage.usd = self.price(model, usage)
        return Response(
            text=text, model=model, provider=self.name, usage=usage, tenant=req.tenant
        )
