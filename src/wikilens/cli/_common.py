"""Shared helpers for CLI commands."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

DEFAULT_DB_PATH = ".wikilens/db"

# Default worker count for the M6 parallel LLM loops. I/O-bound (network)
# work, so a modest pool well above CPU count is appropriate; the executor
# caps each run at this many concurrent calls. ``--workers 1`` forces serial.
DEFAULT_WORKERS = 8


def warn_if_first_run() -> None:
    """Print a one-time notice when local HF models have not been downloaded yet."""
    hf_home = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"))
    hub = hf_home / "hub"
    embedder_cached = any(hub.glob("models--BAAI--bge-small*"))
    reranker_cached = any(hub.glob("models--BAAI--bge-reranker*"))
    if not embedder_cached or not reranker_cached:
        missing = []
        if not embedder_cached:
            missing.append("bge-small-en-v1.5 (embedder, ~130 MB)")
        if not reranker_cached:
            missing.append("bge-reranker-base (reranker, ~140 MB)")
        print(
            "[wikilens] First run: downloading local model(s) — "
            + ", ".join(missing)
            + ". This happens once; models are cached for all subsequent runs.",
            file=sys.stderr,
        )


def add_cost_cache_args(parser: argparse.ArgumentParser) -> None:
    """Register --no-cache and --max-cost flags on a subcommand."""
    parser.add_argument(
        "--no-cache", action="store_true", default=False,
        help="Disable the verdict cache — force fresh LLM calls.",
    )
    parser.add_argument(
        "--max-cost", type=float, default=None,
        help="USD budget ceiling. Abort (exit 2) before exceeding this.",
    )
    parser.add_argument(
        "--workers", type=int, default=DEFAULT_WORKERS,
        help=(
            "Concurrent LLM calls (default: %(default)s). 1 = serial. "
            "Ignored for --judge none (the mock backend always runs serially)."
        ),
    )


def resolve_workers(args: argparse.Namespace, judge_kind: str) -> int:
    """Worker count for the per-item LLM loop, validated and mock-aware.

    The mock backend (``--judge none``) makes no network calls, so concurrency
    buys nothing and would make its stateful, seeded verdict cycling
    non-deterministic — force serial. A non-positive ``--workers`` is clamped
    to 1 so a bad value degrades to serial rather than crashing.
    """
    if judge_kind == "none":
        return 1
    raw = getattr(args, "workers", DEFAULT_WORKERS)
    if raw is None:
        raw = DEFAULT_WORKERS
    return max(1, int(raw))


def open_cost_cache(args: argparse.Namespace, db_dir: str | None = None):
    """Build cache + cost_ctx from parsed CLI args. Lazy-imports cost/cache.

    Returns (cache, cost_ctx). cache is a NullCache when --no-cache.
    """
    from wikilens.cache import open_cache
    from wikilens.cost import CostContext

    effective_dir: str = db_dir or getattr(args, "db", DEFAULT_DB_PATH) or DEFAULT_DB_PATH
    cache = open_cache(no_cache=args.no_cache, db_dir=effective_dir)
    cost_ctx = CostContext(max_cost=getattr(args, "max_cost", None))
    return cache, cost_ctx


def open_index(db_path: str):
    """Open the LanceDB store. Returns (store, embedder, count) or (None, None, exit_code)."""
    from wikilens.embed import BGEEmbedder
    from wikilens.store import LanceDBStore

    embedder = BGEEmbedder()
    store = LanceDBStore(db_path=db_path, dim=embedder.dim)
    try:
        row_count = store.count()
    except (RuntimeError, OSError) as e:
        print(f"Failed to open index at {db_path}: {e}", file=sys.stderr)
        return None, None, 2
    if row_count == 0:
        print(f"No index at {db_path}. Run `wikilens ingest <vault>` first.", file=sys.stderr)
        return None, None, 2
    return store, embedder, row_count
