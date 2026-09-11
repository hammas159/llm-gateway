"""Fake providers.

Every behaviour worth testing in a gateway is a provider behaviour: succeeding,
failing, rate-limiting, being slow, being expensive. Faking them makes the whole
policy layer testable deterministically, in milliseconds, with no API key - which is
why the gateway's own logic can be verified far more thoroughly than a system that
needs a real model to exercise anything.
"""

from __future__ import annotations

import time

from gateway.providers.base import Provider, ProviderError, RateLimited
from gateway.types import Request, Usage


class FakeProvider(Provider):
    def __init__(self, name: str, models: dict[str, tuple[float, float]],
                 *, fail: bool = False, rate_limited: bool = False,
                 delay: float = 0.0, reply: str = "ok") -> None:
        self.name = name
        self.models = models
        self.fail = fail
        self.rate_limited = rate_limited
        self.delay = delay
        self.reply = reply
        self.calls = 0

    def complete(self, req: Request, model: str) -> tuple[str, Usage]:
        self.calls += 1
        if self.rate_limited:
            raise RateLimited(f"{self.name} is rate limiting")
        if self.fail:
            raise ProviderError(f"{self.name} is down")
        if self.delay:
            time.sleep(self.delay)
        # Token counts approximated by words; the gateway only needs them to be
        # proportional, and a real tokenizer would make these tests need a download.
        return self.reply, Usage(
            prompt_tokens=len(req.prompt.split()),
            completion_tokens=len(self.reply.split()),
        )


def local_small(**kw) -> FakeProvider:
    return FakeProvider("ollama", {"local-small": (0.0, 0.0)}, **kw)


def local_large(**kw) -> FakeProvider:
    return FakeProvider("vllm", {"local-large": (0.0, 0.0)}, **kw)


def frontier(**kw) -> FakeProvider:
    # Priced like a real frontier model, so cost assertions mean something.
    return FakeProvider("anthropic", {"frontier": (3.0, 15.0)}, **kw)
