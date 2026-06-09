"""Tests for the on-disk verdict cache (M5).

The cache stores RAW completion text keyed by sha256 over a canonical
(family, model, prompt_version, system, user) tuple. These tests cover:

- the authoritative key constructor (``make_key``) and digest stability,
- the cross-family collision guard (the bug that family-as-discriminator fixes),
- the happy-path get/put round-trip on a real sqlite file,
- the ``--no-cache`` ``NullCache`` sentinel (always miss, no file, no egress),
- graceful degradation on a corrupt sqlite file,
- the shared ``complete_with_cache_and_cost`` helper, whose single most
  important invariant is: a warm cache hit returns BEFORE ``fn()`` runs, so
  ZERO LLM calls happen on a re-run of unchanged inputs.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from wikilens.cache import (
    CACHE_FILENAME,
    PROMPT_VERSION,
    CacheKey,
    NullCache,
    RawCompletion,
    VerdictCache,
    complete_with_cache_and_cost,
    make_key,
    open_cache,
)

# --------------------------------------------------------------------------- #
# Test doubles                                                                #
# --------------------------------------------------------------------------- #


class FakeCostContext:
    """Duck-typed stand-in for the (separately built) CostContext."""

    def __init__(
        self,
        budget_error: Exception | None = None,
        pre_budget_error: Exception | None = None,
    ) -> None:
        self.hits = 0
        self.records: list[dict[str, object]] = []
        self.pre_checks: list[float] = []
        self.releases: list[float] = []
        self._budget_error = budget_error
        self._pre_budget_error = pre_budget_error

    def record_hit(self) -> None:
        self.hits += 1

    def check_before_call(self, next_estimate_usd: float = 0.0) -> None:
        self.pre_checks.append(next_estimate_usd)
        if self._pre_budget_error is not None:
            raise self._pre_budget_error

    def release(self, reserved_usd: float = 0.0) -> None:
        self.releases.append(reserved_usd)

    def record(
        self,
        *,
        family: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        reserved_usd: float = 0.0,
    ) -> None:
        if self._budget_error is not None:
            raise self._budget_error
        self.records.append(
            {
                "family": family,
                "model": model,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
            }
        )


def _key(
    family: str = "contradict",
    model: str = "gpt-4o",
    system: str = "sys",
    user: str = "usr",
) -> CacheKey:
    return make_key(family=family, model=model, system=system, user=user)


# --------------------------------------------------------------------------- #
# make_key / CacheKey.digest                                                  #
# --------------------------------------------------------------------------- #


class TestMakeKey:
    def test_make_key_defaults_prompt_version(self) -> None:
        k = make_key(family="contradict", model="gpt-4o", system="s", user="u")
        assert k.prompt_version == PROMPT_VERSION

    def test_make_key_returns_cache_key(self) -> None:
        assert isinstance(_key(), CacheKey)

    def test_digest_is_64_hex_chars(self) -> None:
        d = _key().digest()
        assert len(d) == 64
        assert all(c in "0123456789abcdef" for c in d)

    def test_digest_is_deterministic(self) -> None:
        assert _key().digest() == _key().digest()

    def test_different_user_different_digest(self) -> None:
        assert _key(user="a").digest() != _key(user="b").digest()

    def test_different_system_different_digest(self) -> None:
        assert _key(system="a").digest() != _key(system="b").digest()

    def test_different_model_different_digest(self) -> None:
        assert _key(model="gpt-4o").digest() != _key(model="gpt-4o-mini").digest()

    def test_prompt_version_bump_invalidates(self) -> None:
        a = make_key(family="f", model="m", system="s", user="u", prompt_version=1)
        b = make_key(family="f", model="m", system="s", user="u", prompt_version=2)
        assert a.digest() != b.digest()

    def test_cross_family_collision_guard(self) -> None:
        """Same model/system/user under different families MUST differ.

        This is the silent cross-family collision bug: self.name is the shared
        literal 'openai'/'claude'/'mock' across all 6 agent families, so the
        family discriminator (not self.name) is what keeps verdicts from one
        command being replayed for another.
        """
        contradict = _key(family="contradict")
        gap = _key(family="gap")
        assert contradict.digest() != gap.digest()

    def test_unit_separator_prevents_boundary_collision(self) -> None:
        """Field concatenation must not collide when boundaries shift.

        Without a separator, (family='ab', model='c') and (family='a',
        model='bc') would hash identically. The \\x1f unit separator prevents
        this.
        """
        a = make_key(family="ab", model="c", system="s", user="u")
        b = make_key(family="a", model="bc", system="s", user="u")
        assert a.digest() != b.digest()

    def test_frozen(self) -> None:
        k = _key()
        with pytest.raises(AttributeError):
            k.family = "other"  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# RawCompletion                                                               #
# --------------------------------------------------------------------------- #


class TestRawCompletion:
    def test_fields(self) -> None:
        rc = RawCompletion(text="hello", prompt_tokens=10, completion_tokens=3)
        assert rc.text == "hello"
        assert rc.prompt_tokens == 10
        assert rc.completion_tokens == 3

    def test_frozen(self) -> None:
        rc = RawCompletion(text="x", prompt_tokens=1, completion_tokens=1)
        with pytest.raises(AttributeError):
            rc.text = "y"  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# VerdictCache (real sqlite, tmp_path)                                        #
# --------------------------------------------------------------------------- #


class TestVerdictCache:
    def test_miss_on_empty(self, tmp_path: Path) -> None:
        with VerdictCache(tmp_path / "c.sqlite3") as cache:
            assert cache.get(_key()) is None

    def test_put_then_get(self, tmp_path: Path) -> None:
        with VerdictCache(tmp_path / "c.sqlite3") as cache:
            k = _key()
            cache.put(k, '{"verdict": false}')
            assert cache.get(k) == '{"verdict": false}'

    def test_get_distinguishes_keys(self, tmp_path: Path) -> None:
        with VerdictCache(tmp_path / "c.sqlite3") as cache:
            cache.put(_key(user="a"), "AAA")
            cache.put(_key(user="b"), "BBB")
            assert cache.get(_key(user="a")) == "AAA"
            assert cache.get(_key(user="b")) == "BBB"

    def test_put_is_idempotent_replace(self, tmp_path: Path) -> None:
        with VerdictCache(tmp_path / "c.sqlite3") as cache:
            k = _key()
            cache.put(k, "first")
            cache.put(k, "second")
            assert cache.get(k) == "second"

    def test_persists_across_connections(self, tmp_path: Path) -> None:
        db = tmp_path / "c.sqlite3"
        with VerdictCache(db) as cache:
            cache.put(_key(), "persisted")
        with VerdictCache(db) as reopened:
            assert reopened.get(_key()) == "persisted"

    def test_stores_family_and_model_columns(self, tmp_path: Path) -> None:
        db = tmp_path / "c.sqlite3"
        with VerdictCache(db) as cache:
            cache.put(_key(family="gap", model="claude-sonnet-4-6"), "x")
        conn = sqlite3.connect(db)
        try:
            row = conn.execute(
                "SELECT family, model FROM entries"
            ).fetchone()
        finally:
            conn.close()
        assert row == ("gap", "claude-sonnet-4-6")

    def test_empty_string_completion_roundtrips(self, tmp_path: Path) -> None:
        with VerdictCache(tmp_path / "c.sqlite3") as cache:
            k = _key()
            cache.put(k, "")
            # Empty string is a stored value, NOT a miss.
            assert cache.get(k) == ""

    def test_accepts_str_path(self, tmp_path: Path) -> None:
        with VerdictCache(str(tmp_path / "c.sqlite3")) as cache:
            cache.put(_key(), "ok")
            assert cache.get(_key()) == "ok"


class TestVerdictCacheCorruption:
    def test_corrupt_file_does_not_crash(self, tmp_path: Path) -> None:
        """A corrupt sqlite file must degrade to always-miss, never crash."""
        db = tmp_path / "broken.sqlite3"
        db.write_bytes(b"this is not a sqlite database header at all")
        cache = VerdictCache(db)
        # Degraded cache behaves like a NullCache.
        assert cache.get(_key()) is None
        cache.put(_key(), "ignored")
        assert cache.get(_key()) is None
        cache.close()

    def test_corrupt_file_warns_on_stderr(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        db = tmp_path / "broken.sqlite3"
        db.write_bytes(b"garbage garbage garbage")
        VerdictCache(db)
        captured = capsys.readouterr()
        # Diagnostics go to stderr (INV2: stdout is machine-readable only).
        assert captured.out == ""
        assert "cache" in captured.err.lower()


# --------------------------------------------------------------------------- #
# NullCache                                                                   #
# --------------------------------------------------------------------------- #


class TestNullCache:
    def test_always_miss(self) -> None:
        cache = NullCache()
        cache.put(_key(), "value")
        assert cache.get(_key()) is None

    def test_context_manager(self) -> None:
        with NullCache() as cache:
            assert cache.get(_key()) is None

    def test_close_is_noop(self) -> None:
        NullCache().close()  # must not raise

    def test_creates_no_file(self, tmp_path: Path) -> None:
        before = set(tmp_path.iterdir())
        NullCache().put(_key(), "x")
        assert set(tmp_path.iterdir()) == before


# --------------------------------------------------------------------------- #
# open_cache                                                                  #
# --------------------------------------------------------------------------- #


class TestOpenCache:
    def test_no_cache_returns_nullcache(self, tmp_path: Path) -> None:
        cache = open_cache(no_cache=True, db_dir=tmp_path)
        assert isinstance(cache, NullCache)

    def test_no_cache_creates_no_file(self, tmp_path: Path) -> None:
        open_cache(no_cache=True, db_dir=tmp_path)
        assert not (tmp_path / ".wikilens").exists()

    def test_enabled_returns_verdict_cache(self, tmp_path: Path) -> None:
        with open_cache(no_cache=False, db_dir=tmp_path) as cache:
            assert isinstance(cache, VerdictCache)

    def test_enabled_creates_sidecar(self, tmp_path: Path) -> None:
        with open_cache(no_cache=False, db_dir=tmp_path) as cache:
            cache.put(_key(), "v")
        assert (tmp_path / ".wikilens" / CACHE_FILENAME).exists()

    def test_enabled_round_trip(self, tmp_path: Path) -> None:
        with open_cache(no_cache=False, db_dir=tmp_path) as cache:
            cache.put(_key(), "stored")
        with open_cache(no_cache=False, db_dir=tmp_path) as reopened:
            assert reopened.get(_key()) == "stored"

    def test_accepts_str_db_dir(self, tmp_path: Path) -> None:
        with open_cache(no_cache=False, db_dir=str(tmp_path)) as cache:
            assert isinstance(cache, VerdictCache)


# --------------------------------------------------------------------------- #
# complete_with_cache_and_cost  (THE shared helper)                           #
# --------------------------------------------------------------------------- #


class TestCompleteWithCacheAndCost:
    def test_cold_miss_calls_fn_and_records(self, tmp_path: Path) -> None:
        cost = FakeCostContext()
        called = {"n": 0}

        def fn() -> RawCompletion:
            called["n"] += 1
            return RawCompletion(text="result", prompt_tokens=12, completion_tokens=4)

        with VerdictCache(tmp_path / "c.sqlite3") as cache:
            out = complete_with_cache_and_cost(
                fn, _key(), cache=cache, cost_ctx=cost
            )
        assert out == "result"
        assert called["n"] == 1
        assert cost.hits == 0
        assert cost.records == [
            {
                "family": "contradict",
                "model": "gpt-4o",
                "prompt_tokens": 12,
                "completion_tokens": 4,
            }
        ]

    def test_warm_hit_returns_before_fn_zero_egress(self, tmp_path: Path) -> None:
        """THE module invariant: a warm hit returns BEFORE fn() runs.

        This is what makes a re-run on an unchanged vault cost ZERO LLM calls.
        We assert fn is never invoked and record() (the cost/egress accounting)
        is never called on the second pass.
        """
        cost = FakeCostContext()
        calls = {"n": 0}

        def fn() -> RawCompletion:
            calls["n"] += 1
            return RawCompletion(text="net", prompt_tokens=5, completion_tokens=1)

        key = _key()
        with VerdictCache(tmp_path / "c.sqlite3") as cache:
            # Cold run populates the cache (one real fn call).
            first = complete_with_cache_and_cost(fn, key, cache=cache, cost_ctx=cost)
            # Warm run must NOT call fn again.
            second = complete_with_cache_and_cost(fn, key, cache=cache, cost_ctx=cost)

        assert first == "net"
        assert second == "net"
        assert calls["n"] == 1  # fn ran exactly once across two passes
        assert cost.hits == 1  # second pass recorded a hit, not a call
        assert len(cost.records) == 1  # only the cold miss was charged

    def test_warm_hit_survives_reopen(self, tmp_path: Path) -> None:
        db = tmp_path / "c.sqlite3"
        key = _key()
        cost = FakeCostContext()

        def fn() -> RawCompletion:
            return RawCompletion(text="persisted", prompt_tokens=1, completion_tokens=1)

        with VerdictCache(db) as cache:
            complete_with_cache_and_cost(fn, key, cache=cache, cost_ctx=cost)

        def boom() -> RawCompletion:  # must never run on a warm hit
            raise AssertionError("fn must not run on a warm cache hit")

        with VerdictCache(db) as reopened:
            out = complete_with_cache_and_cost(
                boom, key, cache=reopened, cost_ctx=cost
            )
        assert out == "persisted"
        assert cost.hits == 1

    def test_nullcache_always_calls_fn(self, tmp_path: Path) -> None:
        cost = FakeCostContext()
        calls = {"n": 0}

        def fn() -> RawCompletion:
            calls["n"] += 1
            return RawCompletion(text="fresh", prompt_tokens=2, completion_tokens=2)

        cache = NullCache()
        complete_with_cache_and_cost(fn, _key(), cache=cache, cost_ctx=cost)
        complete_with_cache_and_cost(fn, _key(), cache=cache, cost_ctx=cost)
        assert calls["n"] == 2  # no caching => fn runs every time
        assert cost.hits == 0

    def test_budget_gate_blocks_before_fn(self, tmp_path: Path) -> None:
        class _BudgetExceededError(Exception):
            pass

        cost = FakeCostContext(pre_budget_error=_BudgetExceededError("cap"))
        called = {"n": 0}

        def fn() -> RawCompletion:
            called["n"] += 1
            return RawCompletion(text="should-not-run", prompt_tokens=1, completion_tokens=1)

        with VerdictCache(tmp_path / "c.sqlite3") as cache, pytest.raises(
            _BudgetExceededError
        ):
            complete_with_cache_and_cost(
                fn,
                _key(),
                cache=cache,
                cost_ctx=cost,
                estimate=lambda: (10, 5),
            )
        assert called["n"] == 0
        assert cost.records == []
        assert cost.pre_checks == [pytest.approx(0.000075)]

    def test_budget_exceeded_propagates_after_egress(self, tmp_path: Path) -> None:
        """If record() raises (budget cap), the helper propagates it.

        NOTE: per the module spec, record() runs AFTER fn() on a miss, so the
        pre-egress budget gate is a cost.py responsibility, not the cache's.
        The cache only guarantees the call is propagated, never swallowed.
        """

        class _BudgetExceededError(Exception):
            pass

        cost = FakeCostContext(budget_error=_BudgetExceededError("over"))

        def fn() -> RawCompletion:
            return RawCompletion(text="x", prompt_tokens=1, completion_tokens=1)

        with VerdictCache(tmp_path / "c.sqlite3") as cache, pytest.raises(
            _BudgetExceededError
        ):
            complete_with_cache_and_cost(fn, _key(), cache=cache, cost_ctx=cost)

    def test_budget_exceeded_does_not_poison_cache(self, tmp_path: Path) -> None:
        """A budget-aborted call must NOT cache its completion.

        If record() raises after fn(), put() must not have run — otherwise a
        verdict that was never paid for / accounted would warm the cache.
        """

        class _BudgetExceededError(Exception):
            pass

        key = _key()
        db = tmp_path / "c.sqlite3"
        cost = FakeCostContext(budget_error=_BudgetExceededError("over"))

        def fn() -> RawCompletion:
            return RawCompletion(
                text="should-not-cache", prompt_tokens=1, completion_tokens=1
            )

        with VerdictCache(db) as cache:
            with pytest.raises(_BudgetExceededError):
                complete_with_cache_and_cost(fn, key, cache=cache, cost_ctx=cost)
            assert cache.get(key) is None

    def test_fn_failure_releases_reservation(self, tmp_path: Path) -> None:
        """If fn() raises, the reserved budget is released (M6 reserve-then-settle).

        A live call that fails before producing usage must hand its tentatively
        reserved budget back via release(), never settle it via record(), and
        never poison the cache.
        """
        cost = FakeCostContext()
        key = _key()

        def boom() -> RawCompletion:
            raise RuntimeError("network died mid-call")

        with VerdictCache(tmp_path / "c.sqlite3") as cache:
            with pytest.raises(RuntimeError, match="network died"):
                complete_with_cache_and_cost(
                    boom,
                    key,
                    cache=cache,
                    cost_ctx=cost,
                    estimate=lambda: (40_000, 0),
                )
            # Reserved on the pre-check, then released on failure; never recorded.
            assert cost.pre_checks == [pytest.approx(0.10)]
            assert cost.releases == [pytest.approx(0.10)]
            assert cost.records == []
            assert cache.get(key) is None
