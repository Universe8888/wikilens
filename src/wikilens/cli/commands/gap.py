"""wikilens gap — find unanswered questions the vault implies."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from wikilens.cli._common import DEFAULT_DB_PATH


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "gap",
        help="Find unanswered questions the vault implies but doesn't answer "
             "(Phase 5.1 plumbing).",
    )
    p.add_argument("vault_path", type=Path)
    p.add_argument("--db", default=DEFAULT_DB_PATH, help="Store path (default: %(default)s)")
    p.add_argument(
        "--judge",
        choices=["none", "openai", "claude"],
        default="openai",
        help=(
            "Generator backend. 'openai' uses OpenAIGenerator (default); "
            "'claude' uses ClaudeGenerator; 'none' uses MockGenerator (no LLM calls)."
        ),
    )
    p.add_argument(
        "--model",
        default="gpt-4o",
        help="Model for --judge openai/claude (default: %(default)s).",
    )
    p.add_argument(
        "--k", type=int, default=None,
        help="K-means cluster count (default: round(sqrt(n_chunks))).",
    )
    p.add_argument(
        "--min-cluster-size", dest="min_cluster_size", type=int, default=3,
        help="Drop clusters with fewer than N chunks (default: %(default)s).",
    )
    p.add_argument(
        "--max-clusters", dest="max_clusters", type=int, default=30,
        help="Cap clusters processed (default: %(default)s).",
    )
    p.add_argument(
        "--top-gaps-per-cluster", dest="top_gaps_per_cluster", type=int, default=3,
        help="Max gap candidates per cluster (default: %(default)s).",
    )
    p.add_argument(
        "--sample", type=int, default=None,
        help="Cap generator calls to the first N clusters (default: no cap).",
    )
    p.add_argument(
        "--seed", type=int, default=42,
        help="K-means random_state for deterministic clusters (default: %(default)s).",
    )
    p.add_argument(
        "--json", action="store_true",
        help="Emit JSON instead of markdown (schema_version: 1).",
    )
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    from wikilens.embed import BGEEmbedder
    from wikilens.gap import generate_gaps
    from wikilens.gap_format import GapReport, format_json, format_markdown
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

    from wikilens.backends import resolve_backend

    generator, err = resolve_backend("gap", args.judge, model=getattr(args, "model", None))
    if err is not None:
        return err

    clusters, findings = generate_gaps(
        store,
        generator,
        k=args.k,
        seed=args.seed,
        min_cluster_size=args.min_cluster_size,
        max_clusters=args.max_clusters,
        top_gaps_per_cluster=args.top_gaps_per_cluster,
        sample=args.sample,
    )
    clusters_processed = (
        min(args.sample, len(clusters))
        if (args.sample is not None and args.sample >= 0)
        else len(clusters)
    )

    report = GapReport(
        vault_root=str(args.vault_path),
        chunks_scanned=row_count,
        clusters=tuple(clusters),
        clusters_processed=clusters_processed,
        findings=tuple(findings),
        generator_name=generator.name,
    )

    if args.json:
        sys.stdout.write(format_json(report))
    else:
        sys.stdout.write(format_markdown(report))

    return 1 if report.total_findings > 0 else 0
