"""wikilens drift — surface notes where beliefs shifted over git history."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from wikilens.cli._common import warn_if_first_run


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "drift",
        help="Surface notes where beliefs shifted over git history.",
    )
    p.add_argument("vault_path", type=Path)
    p.add_argument(
        "--since",
        default=None,
        metavar="REF",
        help="Walk only commits after REF (commit / tag / date). Default: full history.",
    )
    p.add_argument(
        "--judge",
        choices=["none", "openai", "claude"],
        default="openai",
        help=(
            "Judge backend. 'openai' uses OpenAIDriftJudge (default); "
            "'claude' uses ClaudeDriftJudge; 'none' uses MockDriftJudge (no LLM calls)."
        ),
    )
    p.add_argument(
        "--model",
        default="gpt-4o",
        help="Model for --judge openai/claude (default: %(default)s).",
    )
    p.add_argument(
        "--min-score", dest="min_score", type=int, default=4,
        help="Drift score threshold 1-5 (default: %(default)s).",
    )
    p.add_argument(
        "--sample", type=int, default=None,
        help="Cap judge calls to the first N candidate pairs (default: no cap).",
    )
    p.add_argument(
        "--granularity",
        choices=["sentence", "paragraph"],
        default="sentence",
        help="Claim unit for alignment (default: %(default)s).",
    )
    p.add_argument(
        "--only", default=None, metavar="NOTE",
        help="Restrict to a single note path or filename.",
    )
    p.add_argument(
        "--json", action="store_true",
        help="Emit JSON report instead of markdown (schema_version: 1).",
    )
    p.add_argument(
        "-v", "--verbose", action="store_true",
        help="Per-note progress to stderr.",
    )
    p.add_argument("--align-threshold", dest="align_threshold",
                   type=float, default=0.75, help=argparse.SUPPRESS)
    p.add_argument("--identical-threshold", dest="identical_threshold",
                   type=float, default=0.98, help=argparse.SUPPRESS)

    from wikilens.cli._common import add_cost_cache_args

    add_cost_cache_args(p)
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    from wikilens.drift import (
        DEFAULT_ALIGN_THRESHOLD,
        DEFAULT_IDENTICAL_THRESHOLD,
        DriftReport,
        GitError,
        build_candidate_pairs,
        resolve_git_root,
        walk_note_revisions,
    )
    from wikilens.drift_format import format_json, format_markdown
    from wikilens.embed import BGEEmbedder

    vault_path = args.vault_path.resolve()

    try:
        repo_root = resolve_git_root(vault_path)
    except GitError as e:
        print(f"wikilens drift: {e}", file=sys.stderr)
        return 2

    from wikilens.backends import resolve_backend
    from wikilens.cli._common import open_cost_cache

    cache, cost_ctx = open_cost_cache(args, db_dir=str(vault_path))

    judge, err = resolve_backend(
        "drift", args.judge, model=getattr(args, "model", None),
        cache=cache, cost_ctx=cost_ctx,
    )
    if err is not None:
        cache.close()
        return err

    align_threshold = getattr(args, "align_threshold", DEFAULT_ALIGN_THRESHOLD)
    identical_threshold = getattr(args, "identical_threshold", DEFAULT_IDENTICAL_THRESHOLD)
    granularity = getattr(args, "granularity", "sentence")
    only_note: str | None = getattr(args, "only", None) or None
    verbose: bool = getattr(args, "verbose", False)

    note_paths = sorted(vault_path.rglob("*.md"))
    if only_note:
        only_basename = Path(only_note).name
        note_paths = [
            p for p in note_paths
            if p.name == only_basename
            or p.relative_to(vault_path).as_posix() == only_note.replace("\\", "/")
        ]

    warn_if_first_run()
    embedder = BGEEmbedder()

    report = DriftReport(vault=str(vault_path), repo_root=str(repo_root))

    all_candidate_pairs = []
    for note_path in note_paths:
        try:
            rel = note_path.relative_to(repo_root).as_posix()
        except ValueError:
            continue

        revisions = walk_note_revisions(repo_root, rel)
        if len(revisions) < 2:
            continue

        report.walked_commits += len(revisions)

        pairs = build_candidate_pairs(
            revisions,
            embedder,
            align_threshold=align_threshold,
            identical_threshold=identical_threshold,
            granularity=granularity,
        )
        report.pairs_considered += len(pairs)
        if verbose:
            print(f"  {rel}: {len(revisions)} revisions, {len(pairs)} candidate pairs",
                  file=sys.stderr)
        all_candidate_pairs.extend(pairs)

    pairs_to_judge = (
        all_candidate_pairs[:args.sample]
        if args.sample is not None and args.sample >= 0
        else all_candidate_pairs
    )
    report.pairs_filtered = report.pairs_considered - len(pairs_to_judge)

    from wikilens.cli._common import resolve_workers
    from wikilens.drift import judge_drift_pairs

    findings, judged = judge_drift_pairs(
        pairs_to_judge,
        judge,
        min_score=args.min_score,
        workers=resolve_workers(args, args.judge),
    )
    report.pairs_judged += judged
    report.findings.extend(findings)

    if args.json:
        sys.stdout.write(format_json(report))
    else:
        sys.stdout.write(format_markdown(report))

    if cost_ctx.calls > 0 or cost_ctx.cached_calls > 0:
        print(cost_ctx.footer(), file=sys.stderr)

    cache.close()
    return 1 if report.findings else 0
