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
import threading
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
    """Per-invocation token/$ accumulator + budget gate (thread-safe, M6).

    Created ONCE per command in the CLI ``run()`` and threaded only into the
    networked backends. ``Mock*`` never receives one and never calls
    ``record``, so a ``--judge none`` footer shows 0 live calls / $0.0000.

    **Concurrency (M6):** M6 parallelizes the per-item LLM loops with a
    ThreadPoolExecutor, so a single ``CostContext`` is shared across worker
    threads. The budget gate therefore uses **reserve-then-settle** under one
    ``threading.Lock``:

    - ``check_before_call`` atomically checks ``usd + reserved + next`` against
      the cap and, if it fits, **reserves** the estimate. Reserving (not just
      reading committed ``usd``) is what closes the TOCTOU race: two threads
      can no longer both pass the same check, because the first thread's
      reservation is visible to the second under the lock.
    - ``record`` **settles**: releases the matching reservation and adds the
      honest post-call usage.
    - ``release`` frees a reservation when a reserved call fails before
      settling, so a transient error does not permanently waste budget.

    The lock also guards the plain accumulators (``calls``, token counts,
    ``usd``, ``_families``), whose ``+=`` / ``set.add`` are not atomic across
    threads. ``_reserved`` is private bookkeeping and never appears in the
    footer or any JSON.
    """

    max_cost: float | None = None
    calls: int = 0
    cached_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    usd: float = 0.0
    _families: set[str] = field(default_factory=set)
    _reserved: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def would_exceed(self, next_estimate_usd: float = 0.0) -> bool:
        """True if a cap is set and committed+reserved spend + next crosses it.

        Exactly hitting the cap is allowed (``>`` not ``>=``). This is a
        read-only probe; it accounts for outstanding reservations so it is
        consistent with the value the locked gate would compute, but callers
        that need the race-free guarantee must use ``check_before_call``.
        """
        if self.max_cost is None:
            return False
        with self._lock:
            return self.usd + self._reserved + next_estimate_usd > self.max_cost

    def check_before_call(self, next_estimate_usd: float = 0.0) -> None:
        """Atomically reserve budget for the next call, or raise ``BudgetExceeded``.

        Call this immediately before each live LLM call. Under the lock it
        checks ``usd + reserved + next`` against the cap; if it fits, it
        **reserves** ``next_estimate_usd`` and returns, otherwise it raises and
        reserves nothing. Because the reservation is taken under the same lock
        as the check, concurrent callers cannot both pass against the same
        remaining budget — the crossing call never executes (no egress, no
        spend). The caller MUST later either ``record(reserved_usd=...)`` to
        settle or ``release(...)`` to free the reservation.
        """
        if self.max_cost is None:
            return
        with self._lock:
            if self.usd + self._reserved + next_estimate_usd > self.max_cost:
                raise BudgetExceeded(
                    spent_usd=self.usd + self._reserved, max_cost=self.max_cost
                )
            self._reserved += next_estimate_usd

    def release(self, reserved_usd: float = 0.0) -> None:
        """Free a reservation taken by ``check_before_call`` without settling.

        Used when a reserved call fails before producing usage (e.g. a network
        error that exhausts retries), so the budget it tentatively held is
        returned to the pool for other calls.
        """
        if not reserved_usd:
            return
        with self._lock:
            self._reserved = max(0.0, self._reserved - reserved_usd)

    def record(
        self,
        *,
        family: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        reserved_usd: float = 0.0,
    ) -> None:
        """Settle one LIVE (non-cached) call using the returned usage.

        Honest post-call accounting under the lock: releases the matching
        reservation (``reserved_usd``, default 0 for non-gated callers), then
        adds tokens and the USD estimate. ``record`` does not raise, so the
        actual returned usage is always captured faithfully.
        """
        spent = estimate_usd(model, prompt_tokens, completion_tokens)
        with self._lock:
            if reserved_usd:
                self._reserved = max(0.0, self._reserved - reserved_usd)
            self._families.add(family)
            self.calls += 1
            self.prompt_tokens += prompt_tokens
            self.completion_tokens += completion_tokens
            self.usd += spent

    def record_hit(self) -> None:
        """Account for one warm-cache hit: no live call, no tokens, no spend.

        This is the M5 "warm cache reports zero new spend" signal.
        """
        with self._lock:
            self.cached_calls += 1

    def footer(self) -> str:
        """One human-readable line for STDERR (never stdout — INV2)."""
        with self._lock:
            return (
                f"cost: {self.calls} live calls ({self.cached_calls} cached), "
                f"{self.prompt_tokens} prompt + {self.completion_tokens} completion "
                f"tokens, ~${self.usd:.4f}"
            )
