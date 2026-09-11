"""Response cache.

Exact-match on a normalised key, not semantic similarity. Semantic caching sounds
better and is a good way to serve a confidently wrong answer: two prompts that embed
closely can still require different replies - "is X safe for children" and "is X safe
for adults" are near-identical vectors.

Normalisation is therefore conservative: whitespace and case only. Anything cleverer
starts trading correctness for hit rate, and this cache sits in front of every request.
"""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass, field

from ..types import Response

_WS = re.compile(r"\s+")


def cache_key(prompt: str, system: str, model: str, max_tokens: int) -> str:
    canonical = "\x00".join(
        (
            _WS.sub(" ", prompt.strip().lower()),
            _WS.sub(" ", system.strip().lower()),
            model,
            str(max_tokens),
        )
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass
class CacheEntry:
    response: Response
    stored_at: float
    hits: int = 0


@dataclass
class ResponseCache:
    ttl_seconds: float = 3600.0
    max_entries: int = 10_000
    _entries: dict[str, CacheEntry] = field(default_factory=dict)
    hits: int = 0
    misses: int = 0

    def get(self, key: str) -> Response | None:
        entry = self._entries.get(key)
        if entry is None:
            self.misses += 1
            return None
        if time.time() - entry.stored_at > self.ttl_seconds:
            del self._entries[key]
            self.misses += 1
            return None
        entry.hits += 1
        self.hits += 1
        # A copy, so a caller mutating the response cannot corrupt the cache.
        cached = Response(**{**entry.response.__dict__})
        cached.cached = True
        cached.usage.usd = 0.0  # a cache hit costs nothing; reporting otherwise
        return cached  # would inflate every spend figure

    def put(self, key: str, response: Response) -> None:
        if len(self._entries) >= self.max_entries:
            # Evict the oldest. Not LRU: this is a TTL cache where age is the better
            # signal, and an LRU would keep a stale popular answer forever.
            oldest = min(self._entries, key=lambda k: self._entries[k].stored_at)
            del self._entries[oldest]
        self._entries[key] = CacheEntry(response=response, stored_at=time.time())

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return round(self.hits / total, 4) if total else 0.0

    def stats(self) -> dict:
        return {
            "entries": len(self._entries),
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": self.hit_rate,
        }
