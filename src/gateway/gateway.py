"""The gateway: one entry point, every policy applied in a fixed order.

    guardrails(in) -> budget -> cache -> route -> call with fallback -> guardrails(out)
                                                                    -> record -> log

The order is the design. Guardrails run before the budget so a blocked request costs
nothing. The budget runs before the cache so a tenant over their limit cannot keep
being served, which would hide the breach. The cache runs before routing because a hit
makes the routing decision irrelevant.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from .cache import ResponseCache, cache_key
from .policy.budget import BudgetExceeded, BudgetManager, RateLimitExceeded
from .policy.guardrails import check_input, check_output
from .policy.router import Router
from .providers.base import Provider, ProviderError
from .types import Request, Response, Usage


class Blocked(RuntimeError):
    def __init__(self, reason: str, findings: list[str]) -> None:
        self.findings = findings
        super().__init__(reason)


class AllProvidersFailed(RuntimeError):
    def __init__(self, attempts: list[str]) -> None:
        self.attempts = attempts
        super().__init__(f"every provider failed: {', '.join(attempts)}")


@dataclass
class Gateway:
    providers: list[Provider]
    router: Router = field(default_factory=Router)
    budgets: BudgetManager = field(default_factory=BudgetManager)
    cache: ResponseCache = field(default_factory=ResponseCache)
    redact_pii: bool = False
    log: list[Response] = field(default_factory=list)

    def _provider_for(self, model: str) -> Provider | None:
        return next((p for p in self.providers if p.supports(model)), None)

    def complete(self, req: Request) -> Response:
        started = time.perf_counter()

        guard_in = check_input(req.prompt, redact_pii=self.redact_pii)
        if not guard_in.allowed:
            # Logged, so a blocked attempt is visible rather than merely refused.
            blocked = Response(
                text="",
                model="",
                provider="",
                tenant=req.tenant,
                blocked_reason=", ".join(guard_in.findings),
            )
            self.log.append(blocked)
            raise Blocked("request blocked by input guardrails", guard_in.findings)

        prompt = guard_in.text

        # Raises before any spend. The estimate is deliberately crude; its job is to
        # stop one huge request stepping over a nearly exhausted budget.
        self.budgets.check(req.tenant, estimated_usd=len(prompt) / 4 / 1000 * 0.01)

        policy = self.budgets.policy(req.tenant)
        route = self.router.route(prompt, pinned=req.model, allowed=policy.allowed_models)

        if req.use_cache:
            hit = self.cache.get(cache_key(prompt, req.system, route.primary, req.max_tokens))
            if hit is not None:
                hit.latency_ms = int((time.perf_counter() - started) * 1000)
                self.log.append(hit)
                return hit

        attempted: list[str] = []
        last_error: Exception | None = None

        for model in [route.primary, *route.fallbacks]:
            provider = self._provider_for(model)
            if provider is None:
                attempted.append(f"{model}(no provider)")
                continue
            try:
                text, usage = provider.complete(
                    Request(**{**req.__dict__, "prompt": prompt}), model
                )
            except ProviderError as exc:
                # Failing over rather than retrying the same provider: a provider that
                # is down or rate-limiting will still be down on an immediate retry.
                attempted.append(f"{model}({type(exc).__name__})")
                last_error = exc
                continue

            response = provider.make_response(req, model, text, usage)
            guard_out = check_output(response.text)
            response.text = guard_out.text
            response.fallbacks = attempted
            response.latency_ms = int((time.perf_counter() - started) * 1000)

            self.budgets.record(req.tenant, response.usage.usd)
            if req.use_cache:
                self.cache.put(cache_key(prompt, req.system, model, req.max_tokens), response)
            self.log.append(response)
            return response

        raise AllProvidersFailed(attempted) from last_error

    def stats(self) -> dict:
        served = [r for r in self.log if not r.blocked_reason]
        spend = sum(r.usage.usd for r in served)
        by_model: dict[str, int] = {}
        for r in served:
            by_model[r.model] = by_model.get(r.model, 0) + 1
        return {
            "requests": len(self.log),
            "blocked": sum(1 for r in self.log if r.blocked_reason),
            "served": len(served),
            "cache": self.cache.stats(),
            "total_usd": round(spend, 6),
            "usd_per_request": round(spend / len(served), 8) if served else 0.0,
            "by_model": by_model,
            "fallback_rate": round(sum(1 for r in served if r.fallbacks) / len(served), 4)
            if served
            else 0.0,
        }


__all__ = [
    "AllProvidersFailed",
    "Blocked",
    "BudgetExceeded",
    "Gateway",
    "RateLimitExceeded",
    "Request",
    "Response",
    "Usage",
]
