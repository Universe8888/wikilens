"""wikilens CLI entry point."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from wikilens import __version__

DEFAULT_DB_PATH = ".wikilens/db"


def _cmd_ingest(args: argparse.Namespace) -> int:
    # Heavy imports deferred to keep `wikilens --help` fast.
    from wikilens.pipeline import ingest_vault

    report = ingest_vault(
        vault_root=args.vault_path,
        db_path=args.db,
    )
    print(report.summary())
    return 0


def _cmd_query(args: argparse.Namespace) -> int:
    from wikilens.embed import BGEEmbedder
    from wikilens.query import query
    from wikilens.rerank import BGEReranker
    from wikilens.store import LanceDBStore

    embedder = BGEEmbedder()
    store = LanceDBStore(db_path=args.db, dim=embedder.dim)
    if store.count() == 0:
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


def _cmd_stub(name: str, phase: str):
    def _fn(args: argparse.Namespace) -> int:
        print(f"wikilens: '{name}' is not available yet ({phase}).")
        return 2

    return _fn


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wikilens",
        description="Agentic intelligence layer for Markdown/Obsidian vaults.",
    )
    parser.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command")

    # ingest
    p_ingest = sub.add_parser("ingest", help="Index a markdown vault.")
    p_ingest.add_argument("vault_path", type=Path)
    p_ingest.add_argument("--db", default=DEFAULT_DB_PATH, help="Store path (default: %(default)s)")
    p_ingest.set_defaults(func=_cmd_ingest)

    # query
    p_query = sub.add_parser("query", help="Semantic search over an indexed vault.")
    p_query.add_argument("question", type=str)
    p_query.add_argument("--db", default=DEFAULT_DB_PATH, help="Store path (default: %(default)s)")
    p_query.add_argument(
        "--mode",
        choices=["dense", "bm25", "hybrid", "rerank"],
        default="rerank",
        help="Retrieval strategy (default: %(default)s)",
    )
    p_query.add_argument("-k", type=int, default=5, help="Number of results (default: %(default)s)")
    p_query.set_defaults(func=_cmd_query)

    # Stubs for later phases (keep the help surface honest)
    for name, phase in [
        ("audit", "P3"),
        ("contradictions", "P4"),
        ("gaps", "P6"),
        ("benchmark", "P5"),
    ]:
        p = sub.add_parser(name, help=f"({phase} — not implemented)")
        p.set_defaults(func=_cmd_stub(name, phase))

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
