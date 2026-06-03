"""wikilens contradict — find contradicting chunk pairs."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from wikilens.cli._common import DEFAULT_DB_PATH


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "contradict",
        help="Find contradicting chunk pairs in a vault (Phase 4.1 plumbing).",
    )
    p.add_argument("vault_path", type=Path)
    p.add_argument("--db", default=DEFAULT_DB_PATH, help="Store path (default: %(default)s)")
    p.add_argument(
        "--judge",
        choices=["none", "openai", "claude", "ollama"],
        default="openai",
        help=(
            "Judge backend. 'openai' uses OpenAIJudge (default); "
            "'claude' uses ClaudeJudge; 'none' uses MockJudge (no LLM calls)."
        ),
    )
    p.add_argument(
        "--model",
        default="gpt-4o",
        help="Model for --judge openai/claude (default: %(default)s).",
    )
    p.add_argument(
        "--top-k", dest="top_k", type=int, default=10,
        help="Retrieval neighbors per chunk (default: %(default)s).",
    )
    p.add_argument(
        "--min-score", dest="min_score", type=float, default=0.5,
        help="Drop verdicts with score below this threshold (default: %(default)s).",
    )
    p.add_argument(
        "--sample", type=int, default=None,
        help="Cap judge calls to the first N candidate pairs (default: no cap).",
    )
    p.add_argument(
        "--only", default="",
        help="Comma-separated scopes to include (factual,temporal). Default: all.",
    )
    p.add_argument(
        "--json", action="store_true",
        help="Emit JSON instead of markdown (schema_version: 1).",
    )

    from wikilens.cli._common import add_cost_cache_args

    add_cost_cache_args(p)
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    from wikilens.contradict import generate_candidate_pairs
    from wikilens.contradict_format import (
        ALL_SCOPES,
        ContradictReport,
        Finding,
        format_json,
        format_markdown,
    )
    from wikilens.embed import BGEEmbedder
    from wikilens.store import LanceDBStore

    only_tuple: tuple[str, ...] | None = None
    if args.only:
        requested = [c.strip() for c in args.only.split(",") if c.strip()]
        invalid = [c for c in requested if c not in ALL_SCOPES]
        if invalid:
            print(
                f"wikilens contradict: unknown scope(s): {', '.join(invalid)}. "
                f"Valid: {', '.join(ALL_SCOPES)}",
                file=sys.stderr,
            )
            return 2
        only_tuple = tuple(requested)  # type: ignore[assignment]

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

    from wikilens.backends import resolve_backend
    from wikilens.cli._common import open_cost_cache

    cache, cost_ctx = open_cost_cache(args, db_dir=args.db)

    try:
        judge, err = resolve_backend(
            "contradict", args.judge,
            model=getattr(args, "model", None), cache=cache, cost_ctx=cost_ctx,
        )
        if err is not None:
            return err

        pairs = generate_candidate_pairs(store, embedder=embedder, top_k=args.top_k)
        judged_pairs = (
            pairs[: args.sample] if args.sample is not None and args.sample >= 0 else pairs
        )

        findings: list[Finding] = []
        for p in judged_pairs:
            verdict = judge.score_pair(p.a.text, p.b.text)
            if verdict.verdict and verdict.score >= args.min_score:
                findings.append(Finding(pair=p, verdict=verdict))

        report = ContradictReport(
            vault_root=str(args.vault_path),
            chunks_scanned=row_count,
            candidates=len(pairs),
            judged=len(judged_pairs),
            judge_name=judge.name,
            findings=tuple(findings),
        )

        if args.json:
            sys.stdout.write(format_json(report, only=only_tuple))  # type: ignore[arg-type]
        else:
            sys.stdout.write(format_markdown(report, only=only_tuple))  # type: ignore[arg-type]

        if cost_ctx.calls > 0 or cost_ctx.cached_calls > 0:
            print(cost_ctx.footer(), file=sys.stderr)

        return 1 if report.total_findings > 0 else 0
    finally:
        cache.close()
