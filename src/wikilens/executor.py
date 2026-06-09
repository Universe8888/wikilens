"""Bounded, order-preserving parallel map over the per-item LLM loops (M6).

The six agent commands (contradict / gap / drift / concepts / confidence /
answer) each iterate over N items and make one LLM call per item. Those calls
are independent and network-bound, so running them serially wastes wall-clock
proportional to N. ``parallel_map`` runs them over a bounded
``ThreadPoolExecutor`` while preserving two properties the commands rely on:

1. **Input order.** The result list is indexed by input position, never by
   completion order, so each command's existing JSON ordering is unchanged
   whether it runs with 1 worker or 16.
2. **Fail-fast on budget.** If any worker raises (``BudgetExceeded`` first and
   foremost, but any exception), pending futures are cancelled and the
   exception propagates — a budget cap aborts the batch instead of quietly
   letting the tail finish and overspend.

``max_workers=1`` takes a genuinely serial path (no threads): it is the runtime
escape hatch (``--workers 1``) and the regression anchor proving M6 did not
change single-threaded behavior.

Stdlib-only (``concurrent.futures``); no SDK or wikilens-backend import, so this
stays import-light like ``cost.py`` / ``cache.py`` / ``retry.py``.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from concurrent.futures import FIRST_EXCEPTION, ThreadPoolExecutor, wait


def parallel_map[In, Out](
    fn: Callable[[In], Out],
    items: Sequence[In],
    *,
    max_workers: int,
) -> list[Out]:
    """Apply ``fn`` to each item, returning results in INPUT order.

    With ``max_workers == 1`` runs serially in input order. With more workers
    runs over a ``ThreadPoolExecutor`` capped at ``max_workers``; the first
    worker exception cancels still-pending work and propagates. ``fn`` should
    be thread-safe with respect to any shared state it touches (the M6 cost
    gate is — see ``CostContext``).
    """
    if max_workers < 1:
        raise ValueError(f"max_workers must be >= 1, got {max_workers}")
    if not items:
        return []

    if max_workers == 1:
        # True serial path: deterministic, no thread overhead, and the exact
        # semantics the pre-M6 loops had — the regression anchor for --workers 1.
        return [fn(item) for item in items]

    results: list[Out] = [None] * len(items)  # type: ignore[list-item]
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_to_index = {
            pool.submit(fn, item): i for i, item in enumerate(items)
        }
        pending = set(future_to_index)
        try:
            while pending:
                done, pending = wait(pending, return_when=FIRST_EXCEPTION)
                for future in done:
                    # .result() re-raises a worker exception here; the finally
                    # block then cancels everything still pending.
                    results[future_to_index[future]] = future.result()
        except BaseException:
            for future in pending:
                future.cancel()
            raise
    return results
