"""Tests for the --workers flag and resolve_workers (M6 Phase 4).

resolve_workers decides the concurrency for the per-item LLM loop. Two rules
carry weight: the mock backend (--judge none) is forced serial so its stateful
seeded verdicts stay deterministic, and a non-positive value clamps to 1 so a
bad flag degrades to serial instead of crashing the ThreadPoolExecutor.
"""

from __future__ import annotations

import argparse

from wikilens.cli._common import (
    DEFAULT_WORKERS,
    add_cost_cache_args,
    resolve_workers,
)


def _parse(*argv: str) -> argparse.Namespace:
    p = argparse.ArgumentParser()
    add_cost_cache_args(p)
    return p.parse_args(list(argv))


class TestWorkersFlagParsing:
    def test_default_is_default_workers(self) -> None:
        assert _parse().workers == DEFAULT_WORKERS

    def test_explicit_value_parses(self) -> None:
        assert _parse("--workers", "16").workers == 16


class TestResolveWorkers:
    def test_openai_uses_requested(self) -> None:
        assert resolve_workers(_parse("--workers", "6"), "openai") == 6

    def test_claude_uses_requested(self) -> None:
        assert resolve_workers(_parse("--workers", "3"), "claude") == 3

    def test_mock_forced_serial(self) -> None:
        # Concurrency on the mock backend buys nothing and would break the
        # determinism of its seeded, stateful verdict cycling.
        assert resolve_workers(_parse("--workers", "16"), "none") == 1

    def test_default_when_unset(self) -> None:
        assert resolve_workers(_parse(), "openai") == DEFAULT_WORKERS

    def test_zero_clamps_to_one(self) -> None:
        assert resolve_workers(argparse.Namespace(workers=0), "openai") == 1

    def test_negative_clamps_to_one(self) -> None:
        assert resolve_workers(argparse.Namespace(workers=-4), "openai") == 1

    def test_missing_attr_falls_back_to_default(self) -> None:
        assert resolve_workers(argparse.Namespace(), "openai") == DEFAULT_WORKERS

    def test_none_value_falls_back_to_default(self) -> None:
        assert resolve_workers(argparse.Namespace(workers=None), "openai") == DEFAULT_WORKERS
