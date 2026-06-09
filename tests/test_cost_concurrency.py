"""Thread-safety tests for the cost accounting + budget cap (M6 Phase 1).

M6 parallelizes the per-item LLM loops with a ThreadPoolExecutor. A single
``CostContext`` is shared across all worker threads, so its budget gate and
accumulators must be thread-safe. The invariant that matters most:

    Total committed spend NEVER exceeds ``max_cost``, even when N threads
    race the gate simultaneously.

Without a lock the gate is a classic TOCTOU race: every thread reads the same
pre-spend ``usd``, all pass ``check_before_call``, all proceed, and the cap is
blown. These tests force that race with a ``Barrier`` and loop many rounds so a
non-thread-safe implementation fails loudly and reproducibly.
"""

from __future__ import annotations

import threading

from wikilens.cost import BudgetExceeded, CostContext, estimate_usd

# A gpt-4o call of 40_000 prompt tokens / 0 completion tokens costs exactly
# $0.10 (0.0025 * 40). Used so reserve estimate == actual settle cost.
_P_TOKENS = 40_000
_C_TOKENS = 0
_PER_CALL_USD = 0.10


def _assert_per_call_cost() -> None:
    assert estimate_usd("gpt-4o", _P_TOKENS, _C_TOKENS) == _PER_CALL_USD


def _race_workers(ctx: CostContext, n_threads: int) -> int:
    """Fire ``n_threads`` simultaneously, each doing reserve -> settle once.

    Returns the count of workers that committed a live call (passed the gate).
    Uses a Barrier so all threads hit the gate at the same instant — maximum
    contention, which is what surfaces a TOCTOU race. Any non-budget exception
    in a worker is re-raised here so a thread crash can never masquerade as a
    benign "fewer committed" pass.
    """
    barrier = threading.Barrier(n_threads)
    committed = []
    committed_lock = threading.Lock()
    errors: list[BaseException] = []
    est = estimate_usd("gpt-4o", _P_TOKENS, _C_TOKENS)

    def worker() -> None:
        barrier.wait()
        try:
            ctx.check_before_call(est)  # reserve atomically
        except BudgetExceeded:
            return
        except BaseException as exc:  # pragma: no cover - defensive
            errors.append(exc)
            return
        try:
            # Simulate the network call returning, then settle honest usage.
            ctx.record(
                family="contradict",
                model="gpt-4o",
                prompt_tokens=_P_TOKENS,
                completion_tokens=_C_TOKENS,
                reserved_usd=est,
            )
            with committed_lock:
                committed.append(1)
        except BaseException as exc:  # pragma: no cover - defensive
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    if errors:
        raise errors[0]
    return len(committed)


class TestConcurrentBudgetGate:
    def test_per_call_cost_precondition(self) -> None:
        _assert_per_call_cost()

    def test_concurrent_calls_never_exceed_cap(self) -> None:
        """50 threads, $1.00 cap, $0.10/call → at most 10 may commit, ever."""
        for _ in range(25):  # loop to catch intermittent races
            ctx = CostContext(max_cost=1.00)
            committed = _race_workers(ctx, n_threads=50)
            assert ctx.usd <= 1.00 + 1e-9, f"cap blown: usd={ctx.usd}"
            # A correct gate admits EXACTLY 10 (cap / per-call), no fewer:
            # under-admitting would mean a reservation leaked and wasted budget.
            assert committed == 10, f"expected exactly 10 committed, got {committed}"
            assert ctx.calls == committed
            # usd must equal exactly the number of committed calls * per-call.
            assert abs(ctx.usd - committed * _PER_CALL_USD) < 1e-9

    def test_concurrent_records_do_not_lose_increments(self) -> None:
        """No cap: every one of N threads must be counted (no lost += )."""
        for _ in range(25):
            ctx = CostContext(max_cost=None)
            committed = _race_workers(ctx, n_threads=50)
            assert committed == 50
            assert ctx.calls == 50
            assert ctx.prompt_tokens == 50 * _P_TOKENS
            assert ctx.completion_tokens == 50 * _C_TOKENS

    def test_failed_call_releases_reservation(self) -> None:
        """A reserved-but-failed call must free its reservation, not leak it.

        If a worker reserves budget then the call raises before settling, the
        reservation must be released so later calls can still use that budget.
        """
        ctx = CostContext(max_cost=1.00)
        est = estimate_usd("gpt-4o", _P_TOKENS, _C_TOKENS)
        # Reserve 10 calls worth, then release them all (simulating 10 failures).
        for _ in range(10):
            ctx.check_before_call(est)
        for _ in range(10):
            ctx.release(est)
        # Budget fully freed: a fresh reservation against the full cap succeeds.
        ctx.check_before_call(est)
        assert ctx.usd == 0.0  # nothing was ever settled

    def test_reservation_blocks_overcommit_before_settle(self) -> None:
        """Reservations count toward the cap even before any call settles.

        Two outstanding reservations of $0.60 must block a third against a
        $1.00 cap — proving the gate reserves, not just reads committed usd.
        """
        ctx = CostContext(max_cost=1.00)
        ctx.check_before_call(0.60)
        import pytest

        with pytest.raises(BudgetExceeded):
            ctx.check_before_call(0.60)  # 0.60 + 0.60 > 1.00


class TestHelperDoesNotLeakReservations:
    """The M5 helper reserves (check_before_call) then settles (record).

    With reserve-then-settle, ``record`` MUST release the reservation it
    matched, or sequential calls under a cap would accumulate phantom
    reservations and falsely trip ``BudgetExceeded`` long before real spend
    reaches the cap. This guards that regression with a REAL CostContext
    (not the duck-typed fake), exercising the production wiring end to end.
    """

    def test_many_sequential_cheap_calls_under_generous_cap(self, tmp_path) -> None:
        from wikilens.cache import (
            NullCache,
            RawCompletion,
            complete_with_cache_and_cost,
            make_key,
        )

        # Cap of $1.00; each call ~ $0.10 (40k prompt tokens). 8 calls = $0.80,
        # comfortably under cap — must NOT raise if reservations are settled.
        ctx = CostContext(max_cost=1.00)
        cache = NullCache()

        def fn() -> RawCompletion:
            return RawCompletion(
                text="ok", prompt_tokens=_P_TOKENS, completion_tokens=_C_TOKENS
            )

        for i in range(8):
            key = make_key(family="contradict", model="gpt-4o", system="s", user=f"u{i}")
            complete_with_cache_and_cost(
                fn,
                key,
                cache=cache,
                cost_ctx=ctx,
                estimate=lambda: (_P_TOKENS, _C_TOKENS),
            )

        assert ctx.calls == 8
        assert abs(ctx.usd - 0.80) < 1e-9
        # No phantom reservation may remain after all calls settle.
        assert ctx._reserved == 0.0
