"""Shared value objects."""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class Request:
    prompt: str
    tenant: str = "default"
    system: str = ""
    max_tokens: int = 512
    # Caller may pin a model; otherwise the router chooses.
    model: str | None = None
    # Opt out of the cache for requests that must be fresh.
    use_cache: bool = True


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    usd: float = 0.0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass
class Response:
    text: str
    model: str
    provider: str
    usage: Usage = field(default_factory=Usage)
    cached: bool = False
    # Providers tried before this one succeeded. Empty on a first-try success.
    fallbacks: list[str] = field(default_factory=list)
    latency_ms: int = 0
    at: float = field(default_factory=time.time)
    tenant: str = "default"
    blocked_reason: str = ""
