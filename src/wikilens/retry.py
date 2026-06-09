"""Exponential-backoff retry for transient LLM API errors (M6).

Before M6 the backends retried only on malformed JSON, immediately, and had no
notion of a rate limit: a single HTTP 429 propagated straight up and aborted
the whole run. When M6 fans the per-item loops out over a ThreadPoolExecutor
that pressure only grows — more concurrent calls means more 429s.

``with_backoff`` wraps a zero-arg callable and retries it on a caller-supplied
``is_retryable`` predicate with exponentially increasing, jittered delays,
capped at ``max_delay``. Two errors are deliberately NOT transient:

- ``BudgetExceeded`` — terminal by design; retrying would spin against the cap.
- a malformed-JSON ``ValueError`` — handled by each backend's existing
  parse-retry loop (re-prompt with a stricter system message), not by sleeping.

All timing is injectable (``sleep`` / ``jitter``) so tests assert the exact
backoff schedule without waiting. ``is_transient_http_error`` classifies SDK
errors structurally (by ``status_code`` or class name) so this module imports
neither ``openai`` nor ``anthropic`` — keeping ``import wikilens.cli`` light,
consistent with ``cost.py`` / ``cache.py``.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable

from wikilens.cost import BudgetExceeded

# Status codes worth retrying: 429 (rate limit) + the transient 5xx family.
# 529 is Anthropic's "overloaded". 4xx client errors (400/401/403/404/422) are
# the caller's fault and never retried.
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504, 529})

# SDK exception class names that signal a transient condition. Matched by name
# so this module never imports the SDKs (heavy-import deferral, INV6 spirit).
_RETRYABLE_NAMES = frozenset(
    {
        "RateLimitError",
        "APIConnectionError",
        "APITimeoutError",
        "InternalServerError",
        "ServiceUnavailableError",
        "Timeout",
        "ConnectionError",
    }
)

DEFAULT_MAX_ATTEMPTS = 5
DEFAULT_BASE_DELAY = 1.0
DEFAULT_MAX_DELAY = 30.0


def is_transient_http_error(exc: BaseException) -> bool:
    """True if ``exc`` looks like a retryable transient API error.

    Terminal errors short-circuit to ``False`` first: ``BudgetExceeded`` (cap)
    and ``ValueError`` (malformed JSON, owned by the parse-retry loop). Then a
    structural check: a retryable ``status_code``, or a known transient SDK
    exception class name. Everything else is treated as non-transient.
    """
    if isinstance(exc, BudgetExceeded):
        return False
    if isinstance(exc, ValueError):
        return False
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status in _RETRYABLE_STATUS
    return type(exc).__name__ in _RETRYABLE_NAMES


def default_jitter(delay: float) -> float:
    """Full-jitter: a random point in ``[0, delay]`` (AWS-recommended).

    Spreads retries from many concurrent workers so they do not re-collide in
    lockstep ("thundering herd") after a shared rate-limit window.
    """
    return random.uniform(0.0, delay)  # noqa: S311 - jitter, not crypto


def with_backoff[T](
    fn: Callable[[], T],
    *,
    is_retryable: Callable[[BaseException], bool] = is_transient_http_error,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    base_delay: float = DEFAULT_BASE_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
    sleep: Callable[[float], None] = time.sleep,
    jitter: Callable[[float], float] = default_jitter,
) -> T:
    """Call ``fn`` with exponential backoff on retryable errors.

    Tries ``fn`` up to ``max_attempts`` times. After a retryable failure it
    sleeps ``jitter(min(base_delay * 2**i, max_delay))`` (i = 0-based retry
    index) before the next attempt. A non-retryable error, or the final
    attempt's error, propagates unchanged. ``sleep``/``jitter`` are injected so
    tests run instantly and assert the schedule.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")
    last_exc: BaseException | None = None
    for attempt in range(max_attempts):
        try:
            return fn()
        except BaseException as exc:  # noqa: BLE001 - re-raised below unless retryable
            last_exc = exc
            is_last = attempt == max_attempts - 1
            if is_last or not is_retryable(exc):
                raise
            delay = min(base_delay * (2.0**attempt), max_delay)
            sleep(jitter(delay))
    # Unreachable: the loop either returns or raises. Satisfies the type checker.
    assert last_exc is not None
    raise last_exc
