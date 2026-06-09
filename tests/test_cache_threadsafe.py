"""VerdictCache must be safe under concurrent worker-thread access (M6 Phase 4).

M6 runs the per-item LLM loop over a ThreadPoolExecutor, and each worker calls
``complete_with_cache_and_cost`` -> ``cache.get`` / ``cache.put`` on the SAME
shared cache. Python's ``sqlite3`` defaults to ``check_same_thread=True``, which
raises ``ProgrammingError`` the moment a connection created on the main thread
is touched by a worker thread. These tests force that access pattern so a
non-thread-safe cache fails loudly.
"""

from __future__ import annotations

import threading
from pathlib import Path

from wikilens.cache import VerdictCache, make_key


def _key(user: str):
    return make_key(family="contradict", model="gpt-4o", system="s", user=user)


class TestVerdictCacheConcurrency:
    def test_concurrent_put_get_across_threads(self, tmp_path: Path) -> None:
        """50 threads each put then get their own key — no ProgrammingError."""
        errors: list[BaseException] = []
        n = 50
        barrier = threading.Barrier(n)

        with VerdictCache(tmp_path / "c.sqlite3") as cache:

            def worker(i: int) -> None:
                barrier.wait()  # maximize contention
                try:
                    k = _key(f"u{i}")
                    cache.put(k, f"value-{i}")
                    assert cache.get(k) == f"value-{i}"
                except BaseException as exc:  # pragma: no cover - failure path
                    errors.append(exc)

            threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        assert errors == [], f"concurrent cache access raised: {errors[0]!r}"

    def test_all_concurrent_writes_persist(self, tmp_path: Path) -> None:
        """Every concurrent write must be readable afterward (no lost writes)."""
        n = 30
        db = tmp_path / "c.sqlite3"
        with VerdictCache(db) as cache:
            threads = [
                threading.Thread(target=lambda i=i: cache.put(_key(f"k{i}"), f"v{i}"))
                for i in range(n)
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        with VerdictCache(db) as reopened:
            for i in range(n):
                assert reopened.get(_key(f"k{i}")) == f"v{i}"
