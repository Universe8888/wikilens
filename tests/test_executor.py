"""Tests for the bounded parallel-map executor (M6 Phase 3).

M6 replaces the per-item serial LLM loops with ``parallel_map``, a thin wrapper
over ``concurrent.futures.ThreadPoolExecutor`` that:

- preserves INPUT order in the result list regardless of completion order, so
  every command's existing JSON ordering survives parallelization;
- runs ``max_workers=1`` exactly like a serial loop (the escape hatch +
  regression anchor);
- propagates ``BudgetExceeded`` from any worker promptly and stops scheduling
  new work, so a budget cap aborts the batch instead of finishing it;
- surfaces the first non-budget exception too (no silent result drops).

Workers here are pure functions (no LLM, no network) so the tests are fast and
deterministic; thread-safety of the shared cost gate is covered separately in
``test_cost_concurrency.py``.
"""

from __future__ import annotations

import threading

import pytest

from wikilens.cost import BudgetExceeded
from wikilens.executor import parallel_map


class TestParallelMap:
    def test_preserves_input_order(self) -> None:
        # Even though larger inputs "finish" conceptually later, the result
        # list must follow INPUT order, not completion order.
        items = [5, 1, 4, 2, 3]
        out = parallel_map(lambda x: x * 10, items, max_workers=4)
        assert out == [50, 10, 40, 20, 30]

    def test_empty_input_returns_empty(self) -> None:
        assert parallel_map(lambda x: x, [], max_workers=4) == []

    def test_max_workers_one_is_serial_order(self) -> None:
        order: list[int] = []
        parallel_map(lambda x: order.append(x), [3, 1, 2], max_workers=1)
        # Serial path executes in input order.
        assert order == [3, 1, 2]

    def test_all_items_processed(self) -> None:
        out = parallel_map(lambda x: x + 1, list(range(100)), max_workers=8)
        assert out == [x + 1 for x in range(100)]

    def test_actually_runs_concurrently(self) -> None:
        """With max_workers>=N and a barrier, all N must run at once.

        If the executor were secretly serial, the barrier would deadlock and
        the test would time out — so reaching the assert proves concurrency.
        """
        n = 4
        barrier = threading.Barrier(n, timeout=5)

        def wait_at_barrier(_x: int) -> int:
            barrier.wait()  # only releases when all n threads arrive
            return _x

        out = parallel_map(wait_at_barrier, list(range(n)), max_workers=n)
        assert sorted(out) == list(range(n))

    def test_budget_exceeded_propagates(self) -> None:
        def maybe_over(x: int) -> int:
            if x == 7:
                raise BudgetExceeded(spent_usd=5.0, max_cost=5.0)
            return x

        with pytest.raises(BudgetExceeded):
            parallel_map(maybe_over, list(range(20)), max_workers=4)

    def test_budget_exceeded_stops_scheduling_new_work(self) -> None:
        """After a BudgetExceeded, not every item should get to run.

        We can't assert an exact count (timing-dependent), but a cap hit early
        in a large batch must prevent the tail from all executing — otherwise
        'abort on budget' is meaningless.
        """
        started = []
        lock = threading.Lock()

        def worker(x: int) -> int:
            with lock:
                started.append(x)
            if x == 0:
                raise BudgetExceeded(spent_usd=5.0, max_cost=5.0)
            return x

        with pytest.raises(BudgetExceeded):
            parallel_map(worker, list(range(500)), max_workers=2)
        # Far fewer than all 500 should have started before the abort.
        assert len(started) < 500

    def test_first_non_budget_exception_propagates(self) -> None:
        def boom(x: int) -> int:
            if x == 3:
                raise RuntimeError("worker 3 died")
            return x

        with pytest.raises(RuntimeError, match="worker 3 died"):
            parallel_map(boom, list(range(10)), max_workers=4)

    def test_invalid_max_workers_raises(self) -> None:
        with pytest.raises(ValueError, match="max_workers"):
            parallel_map(lambda x: x, [1, 2], max_workers=0)

    def test_abort_does_not_block_on_in_flight_workers(self) -> None:
        """An aborting batch must return promptly, not wait on busy workers.

        Adversarial-verify finding: with `with ThreadPoolExecutor() as pool`,
        __exit__ calls shutdown(wait=True), which blocks until every RUNNING
        worker returns. If those workers are parked in backoff sleep, a
        BudgetExceeded breach hangs for tens of seconds. The fix returns
        promptly (already-running workers can't be force-killed, but our code
        no longer waits on them). We prove it by parking 3 workers on an Event
        and asserting parallel_map raises within a short window.
        """
        release = threading.Event()
        raised: dict[str, bool] = {}

        def worker(x: int) -> int:
            if x == 0:
                raise BudgetExceeded(spent_usd=5.0, max_cost=5.0)
            release.wait(timeout=10)  # simulate a worker parked in backoff
            return x

        def run() -> None:
            try:
                parallel_map(worker, list(range(4)), max_workers=4)
            except BudgetExceeded:
                raised["ok"] = True

        runner = threading.Thread(target=run)
        runner.start()
        runner.join(timeout=3.0)
        try:
            assert raised.get("ok"), (
                "parallel_map did not return within 3s — it blocked on "
                "in-flight workers (shutdown(wait=True) in __exit__)."
            )
        finally:
            # Release the parked workers so they (and the test process) exit.
            release.set()
            runner.join(timeout=10)
