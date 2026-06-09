"""wikilens concepts — find clusters circling an unnamed concept."""

from __future__ import annotations

import argparse
import json as _json
import sys
from pathlib import Path

from wikilens.cli._common import DEFAULT_DB_PATH


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "concepts",
        help="Find clusters of notes circling an unnamed concept and propose the missing term.",
    )
    p.add_argument("vault_path", type=Path)
    p.add_argument(
        "--db",
        default=DEFAULT_DB_PATH,
        metavar="PATH",
        help="LanceDB directory (default: %(default)s). Must be pre-ingested.",
    )
    p.add_argument(
        "--judge",
        choices=["none", "openai", "claude"],
        default="openai",
        help=(
            "Judge backend. 'openai' uses OpenAIConceptJudge (default); "
            "'claude' uses ClaudeConceptJudge; 'none' uses MockConceptJudge (no LLM calls)."
        ),
    )
    p.add_argument(
        "--model",
        default="gpt-4o",
        help="Model for --judge openai/claude (default: %(default)s).",
    )
    p.add_argument(
        "--top-k", dest="top_k", type=int, default=10,
        help="Maximum findings to return, sorted by confidence (default: %(default)s).",
    )
    p.add_argument(
        "--min-cluster-size", dest="min_cluster_size", type=int, default=3,
        help="Discard clusters smaller than this before judging (default: %(default)s).",
    )
    p.add_argument(
        "--max-clusters", dest="max_clusters", type=int, default=20,
        help="Cap on clusters the judge is called for (default: %(default)s).",
    )
    p.add_argument(
        "--absence-threshold", dest="absence_threshold", type=float, default=0.20,
        help=(
            "Keep a finding only when the proposed term appears in fewer than this "
            "fraction of cluster chunks (default: %(default)s)."
        ),
    )
    p.add_argument(
        "--json", action="store_true",
        help="Emit JSON report instead of markdown (schema_version: 1).",
    )

    from wikilens.cli._common import add_cost_cache_args

    add_cost_cache_args(p)
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    from wikilens.concepts import detect_unnamed_concepts

    vault_path = args.vault_path.resolve()
    db_path = getattr(args, "db", DEFAULT_DB_PATH)

    from wikilens.backends import resolve_backend
    from wikilens.cli._common import open_cost_cache

    cache, cost_ctx = open_cost_cache(args, db_dir=db_path)

    judge, err = resolve_backend(
        "concepts", args.judge, model=getattr(args, "model", None),
        cache=cache, cost_ctx=cost_ctx,
    )
    if err is not None:
        cache.close()
        return err

    from wikilens.cli._common import resolve_workers

    try:
        findings = detect_unnamed_concepts(
            db_path=db_path,
            table_name="chunks",
            judge=judge,
            max_clusters=args.max_clusters,
            min_cluster_size=args.min_cluster_size,
            top_k=args.top_k,
            absence_threshold=args.absence_threshold,
            workers=resolve_workers(args, args.judge),
        )
    except Exception as e:
        print(f"wikilens concepts: {e}", file=sys.stderr)
        return 2

    if getattr(args, "json", False):
        report = {
            "schema_version": 1,
            "vault": str(vault_path),
            "findings": [
                {
                    "cluster_id": f.cluster_id,
                    "proposed_term": f.proposed_term,
                    "confidence": f.confidence,
                    "rationale": f.rationale,
                    "supporting_notes": f.supporting_notes,
                    "evidence_chunks": f.evidence_chunks,
                    "term_freq_in_cluster": f.term_freq_in_cluster,
                }
                for f in findings
            ],
            "stats": {
                "total_findings": len(findings),
            },
        }
        print(_json.dumps(report, indent=2))
    else:
        if not findings:
            print("No unnamed concepts detected.")
        else:
            print(f"# Unnamed Concepts — {vault_path.name}\n")
            for i, f in enumerate(findings, 1):
                print(f"## {i}. {f.proposed_term}  (confidence {f.confidence:.2f})")
                print(f"\n{f.rationale}\n")
                print(f"**Notes:** {', '.join(f.supporting_notes)}")
                print(f"**Term frequency in cluster:** {f.term_freq_in_cluster:.0%}\n")

    if cost_ctx.calls > 0 or cost_ctx.cached_calls > 0:
        print(cost_ctx.footer(), file=sys.stderr)

    cache.close()
    return 1 if findings else 0
