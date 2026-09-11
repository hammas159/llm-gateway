"""Per-tenant spend limits and rate limits.

Both are enforced *before* the call, not reconciled after it. A budget checked
afterwards is an invoice, not a limit.

Spend uses a rolling window rather than calendar days: a limit that resets at midnight
UTC is a limit that can be doubled at 23:59.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field


class BudgetExceeded(RuntimeError):
    def __init__(self, tenant: str, limit: float, used: float) -> None:
        self.tenant, self.limit, self.used = tenant, limit, used
        super().__init__(f"tenant {tenant!r} spend limit reached: ${used:.4f} of ${limit:.4f}")


class RateLimitExceeded(RuntimeError):
    def __init__(self, tenant: str, limit: int, window: float) -> None:
        self.tenant, self.limit = tenant, limit
        super().__init__(f"tenant {tenant!r} exceeded {limit} requests per {window:.0f}s")


@dataclass
class TenantPolicy:
    usd_per_window: float = 10.0
    spend_window_seconds: float = 86_400.0
    requests_per_window: int = 600
    rate_window_seconds: float = 60.0
    # Models this tenant may reach. Empty means no restriction.
    allowed_models: frozenset[str] = frozenset()


@dataclass
class BudgetManager:
    policies: dict[str, TenantPolicy] = field(default_factory=dict)
    default: TenantPolicy = field(default_factory=TenantPolicy)
    _spend: dict[str, deque] = field(default_factory=dict)
    _calls: dict[str, deque] = field(default_factory=dict)

    def policy(self, tenant: str) -> TenantPolicy:
        return self.policies.get(tenant, self.default)

    def _prune(self, store: dict[str, deque], tenant: str, window: float) -> deque:
        now = time.time()
        entries = store.setdefault(tenant, deque())
        while entries and now - entries[0][0] > window:
            entries.popleft()
        return entries

    def check(self, tenant: str, *, estimated_usd: float = 0.0) -> None:
        """Raise if this request would breach either limit."""
        p = self.policy(tenant)

        calls = self._prune(self._calls, tenant, p.rate_window_seconds)
        if len(calls) >= p.requests_per_window:
            raise RateLimitExceeded(tenant, p.requests_per_window, p.rate_window_seconds)

        spend = self._prune(self._spend, tenant, p.spend_window_seconds)
        used = sum(amount for _, amount in spend)
        # The estimate is included so a single large request cannot step over the
        # ceiling and only be noticed once the money is gone.
        if used + estimated_usd > p.usd_per_window:
            raise BudgetExceeded(tenant, p.usd_per_window, used + estimated_usd)

    def record(self, tenant: str, usd: float) -> None:
        now = time.time()
        self._calls.setdefault(tenant, deque()).append((now, 1))
        self._spend.setdefault(tenant, deque()).append((now, usd))

    def usage(self, tenant: str) -> dict:
        p = self.policy(tenant)
        calls = self._prune(self._calls, tenant, p.rate_window_seconds)
        spend = self._prune(self._spend, tenant, p.spend_window_seconds)
        return {
            "tenant": tenant,
            "requests_in_window": len(calls),
            "requests_limit": p.requests_per_window,
            "usd_in_window": round(sum(a for _, a in spend), 6),
            "usd_limit": p.usd_per_window,
        }
