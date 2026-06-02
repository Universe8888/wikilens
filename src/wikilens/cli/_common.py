"""Shared helpers for CLI commands."""

from __future__ import annotations

import os
import sys
from pathlib import Path

DEFAULT_DB_PATH = ".wikilens/db"


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
