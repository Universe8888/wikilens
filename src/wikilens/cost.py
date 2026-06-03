"""Per-model price table + token/$ accumulator + pre-egress budget cap (M5).

Stops re-paying compute/$ on unchanged inputs partner: where ``cache.py``
serves a warm verdict for zero egress, this module accounts for the cold
(live) calls and enforces a hard spending ceiling.

Design notes:
- ``estimate_usd`` is pure: ``PRICES.get(model, ZERO_PRICE)``. An unknown
  model never crashes — it estimates $0 but emits a ONE-TIME stderr
  warning so a silent $0 is never invisible.
- The budget gate is PRE-EGRESS: callers call ``would_exceed`` /
  ``check_before_call`` with the upcoming call's estimate and abort BEFORE
  the network egress. ``record`` is honest POST-call accounting against the
  returned ``usage``. This satisfies "abort before exceeding budget" — the
  call that would cross the cap never executes.
- ``BudgetExceeded`` is a leaf exception (subclass of ``Exception`` only):
  the CLI catches it at the command boundary and maps it to exit code 2,
  and it is NOT caught by any handler the CLI uses for findings.
- This module exposes NO JSON serializer by design, so cost can never be
  accidentally injected into the public JSON stats block (which would break
  ``JSON_SCHEMA_VERSION``). Cost reaches the user only via ``footer()`` ->
  stderr.

Stdlib-only at module top (no openai / anthropic / numpy / wikilens
backends), so ``import wikilens.cli`` stays light.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ModelPrice:
    """USD price per 1K tokens for one model id."""

    prompt_usd_per_1k: float
    completion_usd_per_1k: float


@dataclass(frozen=True)
class Usage:
    """Normalized token counts for one completion (provider-agnostic).

    The two SDKs report tokens under different field names; the
    ``from_*_usage`` adapters normalize into this shape. ``total_tokens``
    is always derived so it stays consistent across providers.
    """

    prompt_tokens: int
    completion_tokens: int

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


# Price table keyed by MODEL ID ONLY (globally unique enough, and matches
# how DEFAULT_*_MODEL are centralized in backends.py). Seeded for the two
# centralized defaults; extend here as new models are adopted.
ZERO_PRICE = ModelPrice(0.0, 0.0)
PRICES: dict[str, ModelPrice] = {
    "gpt-4o": ModelPrice(prompt_usd_per_1k=0.0025, completion_usd_per_1k=0.01),
    "claude-sonnet-4-6": ModelPrice(prompt_usd_per_1k=0.003, completion_usd_per_1k=0.015),
}

# One-time dedup set so an unknown model warns once per process, not per call.
_warned_models: set[str] = set()


def from_openai_usage(usage: Any) -> Usage:
    """Adapt an OpenAI ``response.usage`` (prompt/completion_tokens) to ``Usage``.

    Missing or ``None`` usage degrades to zero tokens rather than crashing.
    """
    if usage is None:
        return Usage(prompt_tokens=0, completion_tokens=0)
    return Usage(
        prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
        completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
    )


def from_anthropic_usage(usage: Any) -> Usage:
    """Adapt an Anthropic ``response.usage`` (input/output_tokens) to ``Usage``.

    Anthropic names tokens differently (``input_tokens`` / ``output_tokens``)
    and reports no ``total_tokens``; the ``Usage`` total is derived. Missing
    or ``None`` usage degrades to zero tokens.
    """
    if usage is None:
        return Usage(prompt_tokens=0, completion_tokens=0)
    return Usage(
        prompt_tokens=int(getattr(usage, "input_tokens", 0) or 0),
        completion_tokens=int(getattr(usage, "output_tokens", 0) or 0),
    )


def estimate_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Estimate USD for one call. Pure except for the one-time unknown warning."""
    price = PRICES.get(model)
    if price is None:
        if model not in _warned_models:
            _warned_models.add(model)
            print(
                f"wikilens: no price entry for model {model!r}; "
                "cost estimate will read $0 for it",
                file=sys.stderr,
            )
        price = ZERO_PRICE
    return (
        prompt_tokens / 1000.0 * price.prompt_usd_per_1k
        + completion_tokens / 1000.0 * price.completion_usd_per_1k
    )


class BudgetExceeded(Exception):  # noqa: N818 — spec-mandated public name caught by the CLI
    """Raised by the pre-egress budget gate when the next call would exceed cap.

    Leaf exception: the CLI catches it at the command boundary and returns
    exit code 2 (bad input / config / budget-exceeded). It is deliberately
    NOT a subclass of any error the CLI catches for findings, so it can never
    be silently swallowed into a "findings present" path.
    """

    def __init__(self, spent_usd: float, max_cost: float) -> None:
        self.spent_usd = spent_usd
        self.max_cost = max_cost
        super().__init__(
            f"budget exceeded: committed ~${spent_usd:.4f} would cross "
            f"cap ${max_cost:.4f}; aborting before next call"
        )


@dataclass
class CostContext:
    """Per-invocation token/$ accumulator + budget gate.

    Created ONCE per command in the CLI ``run()`` and threaded only into the
    networked backends. ``Mock*`` never receives one and never calls
    ``record``, so a ``--judge none`` footer shows 0 live calls / $0.0000.
    """

    max_cost: float | None = None
    calls: int = 0
    cached_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    usd: float = 0.0
    _families: set[str] = field(default_factory=set)

    def would_exceed(self, next_estimate_usd: float = 0.0) -> bool:
        """True if a cap is set and committed spend + the next call crosses it.

        Exactly hitting the cap is allowed (``>`` not ``>=``); this is the
        pre-call gate the CLI uses to decide whether to make the next egress.
        """
        if self.max_cost is None:
            return False
        return self.usd + next_estimate_usd > self.max_cost

    def check_before_call(self, next_estimate_usd: float = 0.0) -> None:
        """Raise ``BudgetExceeded`` BEFORE egress if the next call crosses cap.

        Call this immediately before each live LLM call. Because it raises
        before the call runs, the crossing call never executes — no network
        egress, no spend — satisfying "abort before exceeding budget".
        """
        if self.would_exceed(next_estimate_usd):
            assert self.max_cost is not None  # guaranteed by would_exceed
            raise BudgetExceeded(spent_usd=self.usd, max_cost=self.max_cost)

    def record(
        self,
        *,
        family: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> None:
        """Account for one LIVE (non-cached) call using the returned usage.

        Honest post-call accounting: adds tokens and the USD estimate. The
        cap is enforced pre-egress by ``check_before_call``; ``record`` does
        not raise, so the actual returned usage is always captured faithfully.
        """
        self._families.add(family)
        self.calls += 1
        self.prompt_tokens += prompt_tokens
        self.completion_tokens += completion_tokens
        self.usd += estimate_usd(model, prompt_tokens, completion_tokens)

    def record_hit(self) -> None:
        """Account for one warm-cache hit: no live call, no tokens, no spend.

        This is the M5 "warm cache reports zero new spend" signal.
        """
        self.cached_calls += 1

    def footer(self) -> str:
        """One human-readable line for STDERR (never stdout — INV2)."""
        return (
            f"cost: {self.calls} live calls ({self.cached_calls} cached), "
            f"{self.prompt_tokens} prompt + {self.completion_tokens} completion "
            f"tokens, ~${self.usd:.4f}"
        )
