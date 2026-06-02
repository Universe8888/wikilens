"""wikilens answer — draft stub notes that answer gaps."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from wikilens.cli._common import DEFAULT_DB_PATH


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "answer",
        help="Draft stub notes that answer the gaps found by `wikilens gap`.",
    )
    p.add_argument("vault_path", type=Path)
    p.add_argument(
        "--gaps",
        required=True,
        type=Path,
        help="Path to a `wikilens gap --json` output file (required).",
    )
    p.add_argument("--db", default=DEFAULT_DB_PATH, help="Store path (default: %(default)s)")
    p.add_argument(
        "--judge",
        choices=["none", "openai", "claude"],
        default="openai",
        help=(
            "Drafter backend. 'openai' uses OpenAIDrafter (default); "
            "'claude' uses ClaudeDrafter; 'none' uses MockDrafter (no LLM calls)."
        ),
    )
    p.add_argument(
        "--model",
        default="gpt-4o",
        help="Model for --judge openai/claude (default: %(default)s).",
    )
    p.add_argument(
        "--top-k", dest="top_k", type=int, default=8,
        help="Retrieval neighbors per gap (default: %(default)s).",
    )
    p.add_argument(
        "--retrieval-mode", dest="retrieval_mode",
        choices=["dense", "bm25", "hybrid", "rerank"],
        default="rerank",
        help="Retrieval strategy (default: %(default)s).",
    )
    p.add_argument(
        "--min-supporting", dest="min_supporting", type=int, default=2,
        help=(
            "Skip gap if retrieved chunks < N; emit external-research stub "
            "(default: %(default)s)."
        ),
    )
    p.add_argument(
        "--sample", type=int, default=None,
        help="Cap total drafts produced (smoke mode).",
    )
    p.add_argument(
        "--write", action="store_true",
        help="Write stubs to disk. Requires --out.",
    )
    p.add_argument(
        "--out", default=None,
        help="Output directory for --write (required when --write is set).",
    )
    p.add_argument(
        "--json", action="store_true",
        help="Emit JSON report instead of markdown (schema_version: 1).",
    )
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    from wikilens.answer import AnswerReport, draft_answers, load_gaps
    from wikilens.answer_format import (
        CollisionError,
        format_json,
        format_markdown,
        write_stubs,
    )
    from wikilens.embed import BGEEmbedder
    from wikilens.store import LanceDBStore

    if args.write and not args.out:
        print("wikilens answer: --write requires --out <dir>", file=sys.stderr)
        return 2

    try:
        gaps = load_gaps(args.gaps)
    except ValueError as e:
        print(f"wikilens answer: {e}", file=sys.stderr)
        return 2

    if not gaps:
        print("wikilens answer: gaps file contains no findings.", file=sys.stderr)
        return 2

    embedder = BGEEmbedder()
    store = LanceDBStore(db_path=args.db, dim=embedder.dim)
    try:
        row_count = store.count()
    except (RuntimeError, OSError) as e:
        print(f"Failed to open index at {args.db}: {e}", file=sys.stderr)
        return 2
    if row_count == 0:
        print(
            f"No index at {args.db}. Run `wikilens ingest <vault>` first.",
            file=sys.stderr,
        )
        return 2

    from wikilens.backends import DEFAULT_CLAUDE_MODEL, DEFAULT_OPENAI_MODEL, resolve_backend

    drafter, err = resolve_backend("answer", args.judge, model=getattr(args, "model", None))
    if err is not None:
        return err
    if args.judge == "none":
        drafter_model = "mock"
    elif args.judge == "openai":
        drafter_model = getattr(args, "model", None) or DEFAULT_OPENAI_MODEL
    else:
        drafter_model = getattr(args, "model", None) or DEFAULT_CLAUDE_MODEL

    reranker = None
    if args.retrieval_mode == "rerank":
        from wikilens.rerank import BGEReranker

        reranker = BGEReranker()

    drafts = draft_answers(
        gaps,
        store,
        embedder,
        drafter,
        top_k=args.top_k,
        mode=args.retrieval_mode,
        reranker=reranker,
        min_supporting=args.min_supporting,
        sample=args.sample,
        drafter_model=drafter_model,
    )

    report = AnswerReport(
        vault_root=str(args.vault_path),
        gaps_path=str(args.gaps),
        drafter_name=drafter.name,
        model=drafter_model,
        retrieval_mode=args.retrieval_mode,
        top_k=args.top_k,
        min_supporting=args.min_supporting,
        drafts=tuple(drafts),
    )

    if args.json:
        sys.stdout.write(format_json(report))
    else:
        sys.stdout.write(format_markdown(report))

    if args.write:
        out_dir = Path(args.out)
        try:
            written = write_stubs(report, out_dir)
        except CollisionError as e:
            print(f"wikilens answer: {e}", file=sys.stderr)
            return 2
        print(f"Wrote {len(written)} stub(s) to {out_dir}", file=sys.stderr)

    if report.total_skipped > 0 or report.total_external_research > 0:
        return 1
    return 0
