"""wikilens query — semantic search over an indexed vault."""

from __future__ import annotations

import argparse
import sys

from wikilens.cli._common import DEFAULT_DB_PATH, warn_if_first_run


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("query", help="Semantic search over an indexed vault.")
    p.add_argument("question", type=str)
    p.add_argument("--db", default=DEFAULT_DB_PATH, help="Store path (default: %(default)s)")
    p.add_argument(
        "--mode",
        choices=["dense", "bm25", "hybrid", "rerank"],
        default="rerank",
        help="Retrieval strategy (default: %(default)s)",
    )
    p.add_argument("-k", type=int, default=5, help="Number of results (default: %(default)s)")
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    warn_if_first_run()
    from wikilens.embed import BGEEmbedder
    from wikilens.query import query
    from wikilens.rerank import BGEReranker
    from wikilens.store import LanceDBStore

    embedder = BGEEmbedder()
    store = LanceDBStore(db_path=args.db, dim=embedder.dim)
    try:
        row_count = store.count()
    except (RuntimeError, OSError) as e:
        print(f"Failed to open index at {args.db}: {e}", file=sys.stderr)
        return 2
    if row_count == 0:
        print(f"No index at {args.db}. Run `wikilens ingest <vault>` first.", file=sys.stderr)
        return 2

    reranker = BGEReranker() if args.mode == "rerank" else None

    results = query(
        args.question,
        store=store,
        embedder=embedder,
        mode=args.mode,
        k=args.k,
        reranker=reranker,
    )

    if not results:
        print("(no results)")
        return 0

    for r in results:
        heading = " > ".join(r.heading_path) if r.heading_path else "(no heading)"
        print(f"[{r.rank}] {r.source_rel} — {heading}  (score={r.score:.4f})")
        snippet = r.text.strip().replace("\n", " ")
        if len(snippet) > 240:
            snippet = snippet[:240] + "..."
        print(f"    {snippet}\n")
    return 0
