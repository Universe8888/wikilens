"""wikilens confidence — classify claims on a 1-5 epistemic scale."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "confidence",
        help="Classify claims in a vault on a 1-5 epistemic confidence scale.",
    )
    p.add_argument("vault_path", type=Path, help="Path to the vault directory.")
    p.add_argument(
        "--judge",
        choices=["none", "openai", "claude"],
        default="openai",
        help="LLM backend to use (default: openai). 'none' uses the mock judge.",
    )
    p.add_argument(
        "--model",
        default=None,
        help="Override the judge model name.",
    )
    p.add_argument(
        "--threshold",
        type=int,
        default=2,
        metavar="N",
        help="Report claims with level <= N (default: 2; range 1-5).",
    )
    p.add_argument(
        "--sample",
        type=int,
        default=None,
        metavar="N",
        help="Cap total judge calls to N (smoke mode).",
    )
    p.add_argument(
        "--only",
        default=None,
        metavar="NOTE",
        help="Restrict to notes whose basename contains NOTE (case-insensitive).",
    )
    p.add_argument(
        "--min-confidence",
        type=float,
        default=0.0,
        dest="min_confidence",
        metavar="F",
        help="Drop verdicts whose judge confidence is below F (default: 0.0).",
    )
    p.add_argument(
        "--json", action="store_true",
        help="Emit JSON report instead of markdown (schema_version: 1).",
    )
    p.add_argument(
        "-v", "--verbose", action="store_true",
        help="Print progress to stderr.",
    )

    from wikilens.cli._common import add_cost_cache_args

    add_cost_cache_args(p)
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    from wikilens.confidence import run_confidence
    from wikilens.confidence_format import format_json, format_markdown

    vault_path = str(args.vault_path.resolve())

    from wikilens.backends import resolve_backend
    from wikilens.cli._common import open_cost_cache

    cache, cost_ctx = open_cost_cache(args, db_dir=vault_path)

    judge, err = resolve_backend(
        "confidence", args.judge, model=getattr(args, "model", None),
        cache=cache, cost_ctx=cost_ctx,
    )
    if err is not None:
        cache.close()
        return err

    sample: int | None = getattr(args, "sample", None)
    only: str | None = getattr(args, "only", None)
    threshold: int = getattr(args, "threshold", 2)
    min_confidence: float = getattr(args, "min_confidence", 0.0)

    if getattr(args, "verbose", False):
        print(
            f"wikilens confidence: vault={vault_path!r} judge={judge.name!r} "
            f"threshold={threshold} sample={sample}",
            file=sys.stderr,
        )

    from wikilens.cli._common import resolve_workers

    report = run_confidence(
        vault_path=vault_path,
        judge=judge,
        threshold=threshold,
        sample=sample,
        only=only,
        min_confidence=min_confidence,
        workers=resolve_workers(args, args.judge),
    )

    if args.json:
        sys.stdout.write(format_json(report))
    else:
        sys.stdout.write(format_markdown(report))

    if cost_ctx.calls > 0 or cost_ctx.cached_calls > 0:
        print(cost_ctx.footer(), file=sys.stderr)

    cache.close()
    return 1 if report.has_findings else 0
