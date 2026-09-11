"""Model routing.

The economics of an LLM application are dominated by one fact: most requests are easy
and a small minority are hard, while a flat model choice pays the hard-request price
for all of them. Routing easy work to a small local model and reserving the frontier
model for genuinely hard requests is usually a larger saving than any prompt
optimisation.

Difficulty is estimated from the request, deterministically. A model-based classifier
would be more accurate and would also add a model call to every request, which is the
cost the router exists to avoid.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import IntEnum


class Difficulty(IntEnum):
    EASY = 0
    MEDIUM = 1
    HARD = 2


# Signals of genuine difficulty: multi-step reasoning, long context, code, analysis.
_HARD_SIGNALS = [
    re.compile(r"\b(prove|derive|analyse|analyze|critique|refactor|optimi[sz]e)\b", re.I),
    re.compile(r"\b(step[- ]by[- ]step|chain of thought|reason through)\b", re.I),
    re.compile(r"```"),  # code block
    re.compile(r"\b(architecture|trade[- ]?off|design a|implement a)\b", re.I),
]

# Signals of triviality.
_EASY_SIGNALS = [
    re.compile(r"^\s*(hi|hello|hey|thanks|thank you|ok|okay)\b", re.I),
    re.compile(r"^\s*(what|who|when|where)\s+is\s+\w+\s*\??\s*$", re.I),
    re.compile(r"\b(translate|summari[sz]e|rephrase|spell[- ]?check)\b", re.I),
]


def estimate_difficulty(prompt: str) -> Difficulty:
    words = len(prompt.split())

    if any(p.search(prompt) for p in _HARD_SIGNALS):
        return Difficulty.HARD
    # Length alone is a reasonable proxy once the explicit signals are exhausted.
    if words > 300:
        return Difficulty.HARD
    if any(p.search(prompt) for p in _EASY_SIGNALS) and words < 40:
        return Difficulty.EASY
    if words < 25:
        return Difficulty.EASY
    return Difficulty.MEDIUM


@dataclass
class Route:
    """Which model to try, and what to try after it fails."""

    primary: str
    fallbacks: list[str] = field(default_factory=list)
    difficulty: Difficulty = Difficulty.MEDIUM
    reason: str = ""


@dataclass
class Router:
    # difficulty -> ordered model preference, cheapest capable first
    tiers: dict[Difficulty, list[str]] = field(
        default_factory=lambda: {
            Difficulty.EASY: ["local-small", "local-large", "frontier"],
            Difficulty.MEDIUM: ["local-large", "frontier", "local-small"],
            Difficulty.HARD: ["frontier", "local-large"],
        }
    )

    def route(self, prompt: str, *, pinned: str | None = None,
              allowed: frozenset[str] = frozenset()) -> Route:
        if pinned:
            # An explicit choice is honoured, but still gets a fallback chain: a
            # pinned model that is down should degrade, not fail.
            chain = [m for m in self.tiers[Difficulty.MEDIUM] if m != pinned]
            return Route(pinned, chain, Difficulty.MEDIUM, "pinned by caller")

        difficulty = estimate_difficulty(prompt)
        chain = list(self.tiers[difficulty])

        if allowed:
            chain = [m for m in chain if m in allowed]
            if not chain:
                # The tier's preferred models are all off-limits for this tenant. That
                # must not mean "no answer": a tenant restricted to a small model
                # should still be able to ask a hard question and get the best they
                # are permitted. Fall back to every allowed model, in the order the
                # router prefers overall.
                seen: list[str] = []
                for tier in (Difficulty.HARD, Difficulty.MEDIUM, Difficulty.EASY):
                    for model in self.tiers[tier]:
                        if model in allowed and model not in seen:
                            seen.append(model)
                chain = seen
            if not chain:
                # Genuinely nothing to call: the tenant permits models this router
                # does not know about. Failing is correct - silently upgrading to a
                # model they may not pay for would be worse.
                raise ValueError(
                    f"no permitted model for this request; tenant allows {sorted(allowed)}"
                )

        return Route(
            primary=chain[0],
            fallbacks=chain[1:],
            difficulty=difficulty,
            reason=f"difficulty={difficulty.name.lower()}",
        )
