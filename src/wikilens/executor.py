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
   foremost, but any exception), still-queued futures are cancelled and the
   exception propagates promptly — without blocking on already-running workers.
   Those in-flight workers cannot be force-killed and finish in the background,
   but the per-call budget gate (``CostContext.check_before_call``) blocks any
   NEW crossing egress, so a cap abort stops scheduling new work and keeps
   total spend bounded rather than letting the whole tail finish.

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
    worker exception cancels still-pending work and propagates **promptly** —
    it does NOT block waiting on already-running workers (which may be parked
    in a backoff sleep). Already-running workers cannot be force-killed, so
    they finish in the background, but a budget abort no longer hangs the call
    for tens of seconds. ``fn`` should be thread-safe with respect to any
    shared state it touches (the M6 cost gate is — see ``CostContext``).
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
    # NB: deliberately NOT a `with ThreadPoolExecutor() as pool` block —
    # its __exit__ calls shutdown(wait=True), which blocks until every running
    # worker returns. On an exception (e.g. BudgetExceeded) that would hang the
    # abort behind workers parked in backoff sleep. We shut down explicitly:
    # wait=True on success, wait=False + cancel_futures=True on abort.
    pool = ThreadPoolExecutor(max_workers=max_workers)
    try:
        future_to_index = {pool.submit(fn, item): i for i, item in enumerate(items)}
        pending = set(future_to_index)
        while pending:
            done, pending = wait(pending, return_when=FIRST_EXCEPTION)
            for future in done:
                # .result() re-raises a worker exception here; the except
                # block then cancels pending work and returns without waiting.
                results[future_to_index[future]] = future.result()
    except BaseException:
        # Drop still-queued work and return immediately. Running workers can't
        # be cancelled, but we don't wait for them — the per-call budget gate
        # still blocks any NEW crossing egress, so spend stays bounded.
        pool.shutdown(wait=False, cancel_futures=True)
        raise
    else:
        pool.shutdown(wait=True)
    return results
