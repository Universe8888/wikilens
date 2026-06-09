"""Tests for the exponential-backoff retry helper (M6 Phase 2).

Today's backends retry only on malformed JSON, immediately, with no rate-limit
handling: a single 429 aborts the whole run. M6 adds ``with_backoff`` so a
transient error (429 / 5xx / connection drop) is retried with exponentially
increasing, jittered delays, while a terminal error (budget cap, programmer
bug) is never retried.

All timing is injected: ``sleep`` is a recorder and ``jitter`` is identity, so
these tests never actually wait and assert the exact backoff schedule.
"""

from __future__ import annotations

import pytest

from wikilens.cost import BudgetExceeded
from wikilens.retry import is_transient_http_error, with_backoff


class _Status:
    """Duck-typed SDK error carrying a status_code (OpenAI/Anthropic shape)."""

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class RateLimitError(Exception):
    """Mimics openai/anthropic RateLimitError by class name (structural match)."""


class APIConnectionError(Exception):
    pass


class _Recorder:
    def __init__(self) -> None:
        self.delays: list[float] = []

    def __call__(self, d: float) -> None:
        self.delays.append(d)


def _always_retry(_exc: BaseException) -> bool:
    return True


class TestWithBackoff:
    def test_succeeds_first_try_no_sleep(self) -> None:
        sleep = _Recorder()
        result = with_backoff(
            lambda: "ok", is_retryable=_always_retry, sleep=sleep, jitter=lambda d: d
        )
        assert result == "ok"
        assert sleep.delays == []

    def test_retries_then_succeeds(self) -> None:
        attempts = {"n": 0}

        def flaky() -> str:
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise RateLimitError("429")
            return "success"

        sleep = _Recorder()
        result = with_backoff(
            flaky,
            is_retryable=_always_retry,
            base_delay=1.0,
            sleep=sleep,
            jitter=lambda d: d,
        )
        assert result == "success"
        assert attempts["n"] == 3
        # Two backoffs before the third (successful) attempt: 1.0, 2.0.
        assert sleep.delays == [1.0, 2.0]

    def test_exhausts_attempts_and_reraises_last(self) -> None:
        def always_429() -> str:
            raise RateLimitError("still 429")

        sleep = _Recorder()
        with pytest.raises(RateLimitError, match="still 429"):
            with_backoff(
                always_429,
                is_retryable=_always_retry,
                max_attempts=4,
                base_delay=1.0,
                sleep=sleep,
                jitter=lambda d: d,
            )
        # 4 attempts -> 3 sleeps between them: 1, 2, 4.
        assert sleep.delays == [1.0, 2.0, 4.0]

    def test_non_retryable_raises_immediately(self) -> None:
        def boom() -> str:
            raise ValueError("malformed JSON, not transient")

        sleep = _Recorder()
        with pytest.raises(ValueError, match="malformed"):
            with_backoff(
                boom,
                is_retryable=is_transient_http_error,
                sleep=sleep,
                jitter=lambda d: d,
            )
        assert sleep.delays == []  # never slept, never retried

    def test_budget_exceeded_is_never_retried(self) -> None:
        """A budget cap is terminal — retrying would spin against the cap."""

        def over_budget() -> str:
            raise BudgetExceeded(spent_usd=5.0, max_cost=5.0)

        sleep = _Recorder()
        with pytest.raises(BudgetExceeded):
            with_backoff(
                over_budget,
                is_retryable=is_transient_http_error,
                sleep=sleep,
                jitter=lambda d: d,
            )
        assert sleep.delays == []

    def test_delay_capped_at_max_delay(self) -> None:
        def always_fail() -> str:
            raise RateLimitError("x")

        sleep = _Recorder()
        with pytest.raises(RateLimitError):
            with_backoff(
                always_fail,
                is_retryable=_always_retry,
                max_attempts=6,
                base_delay=1.0,
                max_delay=4.0,
                sleep=sleep,
                jitter=lambda d: d,
            )
        # 1, 2, 4, then capped at 4, 4.
        assert sleep.delays == [1.0, 2.0, 4.0, 4.0, 4.0]

    def test_jitter_applied_to_each_delay(self) -> None:
        def always_fail() -> str:
            raise RateLimitError("x")

        sleep = _Recorder()
        with pytest.raises(RateLimitError):
            with_backoff(
                always_fail,
                is_retryable=_always_retry,
                max_attempts=3,
                base_delay=1.0,
                sleep=sleep,
                jitter=lambda d: d * 0.5,  # deterministic half-jitter
            )
        assert sleep.delays == [0.5, 1.0]

    def test_max_attempts_one_means_no_retry(self) -> None:
        attempts = {"n": 0}

        def once() -> str:
            attempts["n"] += 1
            raise RateLimitError("x")

        sleep = _Recorder()
        with pytest.raises(RateLimitError):
            with_backoff(
                once,
                is_retryable=_always_retry,
                max_attempts=1,
                sleep=sleep,
                jitter=lambda d: d,
            )
        assert attempts["n"] == 1
        assert sleep.delays == []


class TestIsTransientHttpError:
    @pytest.mark.parametrize("code", [429, 500, 502, 503, 504, 529])
    def test_retryable_status_codes(self, code: int) -> None:
        assert is_transient_http_error(_Status(code)) is True

    @pytest.mark.parametrize("code", [400, 401, 403, 404, 422])
    def test_client_errors_not_retryable(self, code: int) -> None:
        assert is_transient_http_error(_Status(code)) is False

    def test_rate_limit_error_by_class_name(self) -> None:
        assert is_transient_http_error(RateLimitError("429")) is True

    def test_connection_error_by_class_name(self) -> None:
        assert is_transient_http_error(APIConnectionError("dropped")) is True

    def test_value_error_not_transient(self) -> None:
        # Malformed-JSON ValueError is handled by the parse-retry loop, not here.
        assert is_transient_http_error(ValueError("bad json")) is False

    def test_budget_exceeded_not_transient(self) -> None:
        assert is_transient_http_error(BudgetExceeded(spent_usd=1.0, max_cost=1.0)) is False
