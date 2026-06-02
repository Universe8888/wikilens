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
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    from wikilens.drift import (
        DEFAULT_ALIGN_THRESHOLD,
        DEFAULT_IDENTICAL_THRESHOLD,
        DriftEvent,
        DriftReport,
        GitError,
        build_candidate_pairs,
        resolve_git_root,
        walk_note_revisions,
    )
    from wikilens.drift_format import format_json, format_markdown
    from wikilens.drift_judge import DriftVerdict
    from wikilens.embed import BGEEmbedder

    vault_path = args.vault_path.resolve()

    try:
        repo_root = resolve_git_root(vault_path)
    except GitError as e:
        print(f"wikilens drift: {e}", file=sys.stderr)
        return 2

    from wikilens.backends import resolve_backend

    judge, err = resolve_backend("drift", args.judge, model=getattr(args, "model", None))
    if err is not None:
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

    for pair in pairs_to_judge:
        before_date = str(pair.before.timestamp)
        after_date = str(pair.after.timestamp)
        verdict: DriftVerdict = judge.score_pair(
            pair.note_rel,
            pair.before_claim,
            before_date,
            pair.after_claim,
            after_date,
        )
        report.pairs_judged += 1
        if verdict.drift and verdict.score >= args.min_score:
            report.findings.append(
                DriftEvent(
                    note_rel=pair.note_rel,
                    before=pair.before,
                    after=pair.after,
                    before_claim=pair.before_claim,
                    after_claim=pair.after_claim,
                    drift_type=verdict.type,
                    score=verdict.score,
                    reasoning=verdict.reasoning,
                )
            )

    if args.json:
        sys.stdout.write(format_json(report))
    else:
        sys.stdout.write(format_markdown(report))

    return 1 if report.findings else 0
