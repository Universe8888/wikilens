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


def _cmd_audit(args: argparse.Namespace) -> int:
    from wikilens.audit import audit_vault
    from wikilens.audit_format import ALL_CLASSES, format_json, format_markdown

    only_tuple: tuple[str, ...] | None = None
    if args.only:
        requested = [c.strip() for c in args.only.split(",") if c.strip()]
        invalid = [c for c in requested if c not in ALL_CLASSES]
        if invalid:
            print(
                f"wikilens audit: unknown class(es): {', '.join(invalid)}. "
                f"Valid: {', '.join(ALL_CLASSES)}",
                file=sys.stderr,
            )
            return 2
        only_tuple = tuple(requested)  # type: ignore[assignment]

    report = audit_vault(args.vault_path)

    if args.json:
        sys.stdout.write(format_json(report, only=only_tuple))  # type: ignore[arg-type]
    else:
        sys.stdout.write(format_markdown(report, only=only_tuple))  # type: ignore[arg-type]

    return 1 if report.total_findings > 0 else 0


def _cmd_contradict(args: argparse.Namespace) -> int:
    from wikilens.contradict import generate_candidate_pairs
    from wikilens.contradict_format import (
        ALL_SCOPES,
        ContradictReport,
        Finding,
        format_json,
        format_markdown,
    )
    from wikilens.embed import BGEEmbedder
    from wikilens.judge import Judge, MockJudge
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

    # Resolve judge backend. Phase 4.1 ships only MockJudge; ClaudeJudge
    # and OllamaJudge are wired in Phase 4.2.
    judge: Judge
    if args.judge == "none":
        judge = MockJudge()
    elif args.judge == "openai":
        from wikilens.judge import OpenAIJudge

        try:
            model = getattr(args, "model", None) or "gpt-4o"
            judge = OpenAIJudge(model=model)
        except (EnvironmentError, ImportError) as e:
            print(f"wikilens contradict: {e}", file=sys.stderr)
            return 2
    elif args.judge == "claude":
        from wikilens.judge import ClaudeJudge

        try:
            model = getattr(args, "model", None) or "claude-sonnet-4-6"
            judge = ClaudeJudge(model=model)
        except (EnvironmentError, ImportError) as e:
            print(f"wikilens contradict: {e}", file=sys.stderr)
            return 2
    elif args.judge == "ollama":
        print(
            "wikilens contradict: --judge ollama is not yet implemented. "
            "Use --judge none, --judge openai, or --judge claude.",
            file=sys.stderr,
        )
        return 2
    else:
        print(f"wikilens contradict: unknown judge: {args.judge!r}", file=sys.stderr)
        return 2

    pairs = generate_candidate_pairs(store, embedder=embedder, top_k=args.top_k)
    if args.sample is not None and args.sample >= 0:
        judged_pairs = pairs[: args.sample]
    else:
        judged_pairs = pairs

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

    return 1 if report.total_findings > 0 else 0


def _cmd_gap(args: argparse.Namespace) -> int:
    from wikilens.embed import BGEEmbedder
    from wikilens.gap import generate_gaps
    from wikilens.gap_format import GapReport, format_json, format_markdown
    from wikilens.generator import Generator, MockGenerator
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

    # Resolve generator backend. Phase 5.1 ships only MockGenerator;
    # ClaudeGenerator lands in Phase 5.2.
    generator: Generator
    if args.judge == "none":
        generator = MockGenerator()
    elif args.judge == "openai":
        from wikilens.generator import OpenAIGenerator

        try:
            model = getattr(args, "model", None) or "gpt-4o"
            generator = OpenAIGenerator(model=model)
        except (EnvironmentError, ImportError) as e:
            print(f"wikilens gap: {e}", file=sys.stderr)
            return 2
    elif args.judge == "claude":
        from wikilens.generator import ClaudeGenerator

        try:
            model = getattr(args, "model", None) or "claude-sonnet-4-6"
            generator = ClaudeGenerator(model=model)
        except (EnvironmentError, ImportError) as e:
            print(f"wikilens gap: {e}", file=sys.stderr)
            return 2
    else:
        print(f"wikilens gap: unknown judge: {args.judge!r}", file=sys.stderr)
        return 2

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


def _cmd_answer(args: argparse.Namespace) -> int:
    from wikilens.answer import AnswerReport, draft_answers, load_gaps
    from wikilens.answer_format import (
        CollisionError,
        format_json,
        format_markdown,
        write_stubs,
    )
    from wikilens.drafter import Drafter, MockDrafter
    from wikilens.embed import BGEEmbedder
    from wikilens.store import LanceDBStore

    # Validate --write / --out combination.
    if args.write and not args.out:
        print(
            "wikilens answer: --write requires --out <dir>",
            file=sys.stderr,
        )
        return 2

    # Load gaps file.
    try:
        gaps = load_gaps(args.gaps)
    except ValueError as e:
        print(f"wikilens answer: {e}", file=sys.stderr)
        return 2

    if not gaps:
        print("wikilens answer: gaps file contains no findings.", file=sys.stderr)
        return 2

    # Open the vector store.
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

    # Resolve drafter backend.
    drafter: Drafter
    drafter_model: str
    if args.judge == "none":
        drafter = MockDrafter()
        drafter_model = "mock"
    elif args.judge == "openai":
        from wikilens.drafter import OpenAIDrafter

        try:
            model = getattr(args, "model", None) or "gpt-4o"
            drafter = OpenAIDrafter(model=model)
            drafter_model = model
        except (EnvironmentError, ImportError) as e:
            print(f"wikilens answer: {e}", file=sys.stderr)
            return 2
    elif args.judge == "claude":
        from wikilens.drafter import ClaudeDrafter

        try:
            model = getattr(args, "model", None) or "claude-sonnet-4-6"
            drafter = ClaudeDrafter(model=model)
            drafter_model = model
        except (EnvironmentError, ImportError) as e:
            print(f"wikilens answer: {e}", file=sys.stderr)
            return 2
    else:
        print(f"wikilens answer: unknown judge: {args.judge!r}", file=sys.stderr)
        return 2

    # Reranker only for rerank mode.
    reranker = None
    if args.retrieval_mode == "rerank":
        from wikilens.rerank import BGEReranker

        reranker = BGEReranker()

    # Run the pipeline.
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

    # Output.
    if args.json:
        sys.stdout.write(format_json(report))
    else:
        sys.stdout.write(format_markdown(report))

    # Optional file write.
    if args.write:
        out_dir = Path(args.out)
        try:
            written = write_stubs(report, out_dir)
        except CollisionError as e:
            print(f"wikilens answer: {e}", file=sys.stderr)
            return 2
        print(
            f"Wrote {len(written)} stub(s) to {out_dir}",
            file=sys.stderr,
        )

    # Exit code: 0 = all strong/thin, 1 = any external-research or skipped.
    if report.total_skipped > 0 or report.total_external_research > 0:
        return 1
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

    # audit (P3)
    p_audit = sub.add_parser(
        "audit",
        help="Find broken, one-way, orphan, and shadowed wikilinks in a vault.",
    )
    p_audit.add_argument("vault_path", type=Path)
    p_audit.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of markdown (schema is stable; see audit_format.py).",
    )
    p_audit.add_argument(
        "--only",
        default="",
        help=(
            "Comma-separated defect classes to include "
            "(broken,one-way,orphan,shadowed). Default: all."
        ),
    )
    p_audit.set_defaults(func=_cmd_audit)

    # contradict (P4)
    p_contradict = sub.add_parser(
        "contradict",
        help="Find contradicting chunk pairs in a vault (Phase 4.1 plumbing).",
    )
    p_contradict.add_argument("vault_path", type=Path)
    p_contradict.add_argument(
        "--db", default=DEFAULT_DB_PATH, help="Store path (default: %(default)s)"
    )
    p_contradict.add_argument(
        "--judge",
        choices=["none", "openai", "claude", "ollama"],
        default="openai",
        help=(
            "Judge backend. 'openai' uses OpenAIJudge (default); "
            "'claude' uses ClaudeJudge; 'none' uses MockJudge (no LLM calls)."
        ),
    )
    p_contradict.add_argument(
        "--model",
        default="gpt-4o",
        help="Model for --judge openai/claude (default: %(default)s).",
    )
    p_contradict.add_argument(
        "--top-k", dest="top_k", type=int, default=10,
        help="Retrieval neighbors per chunk (default: %(default)s).",
    )
    p_contradict.add_argument(
        "--min-score", dest="min_score", type=float, default=0.5,
        help="Drop verdicts with score below this threshold (default: %(default)s).",
    )
    p_contradict.add_argument(
        "--sample", type=int, default=None,
        help="Cap judge calls to the first N candidate pairs (default: no cap).",
    )
    p_contradict.add_argument(
        "--only", default="",
        help="Comma-separated scopes to include (factual,temporal). Default: all.",
    )
    p_contradict.add_argument(
        "--json", action="store_true",
        help="Emit JSON instead of markdown (schema_version: 1).",
    )
    p_contradict.set_defaults(func=_cmd_contradict)

    # gap (P5)
    p_gap = sub.add_parser(
        "gap",
        help="Find unanswered questions the vault implies but doesn't answer "
             "(Phase 5.1 plumbing).",
    )
    p_gap.add_argument("vault_path", type=Path)
    p_gap.add_argument(
        "--db", default=DEFAULT_DB_PATH, help="Store path (default: %(default)s)"
    )
    p_gap.add_argument(
        "--judge",
        choices=["none", "openai", "claude"],
        default="openai",
        help=(
            "Generator backend. 'openai' uses OpenAIGenerator (default); "
            "'claude' uses ClaudeGenerator; 'none' uses MockGenerator (no LLM calls)."
        ),
    )
    p_gap.add_argument(
        "--model",
        default="gpt-4o",
        help="Model for --judge openai/claude (default: %(default)s).",
    )
    p_gap.add_argument(
        "--k", type=int, default=None,
        help="K-means cluster count (default: round(sqrt(n_chunks))).",
    )
    p_gap.add_argument(
        "--min-cluster-size", dest="min_cluster_size", type=int, default=3,
        help="Drop clusters with fewer than N chunks (default: %(default)s).",
    )
    p_gap.add_argument(
        "--max-clusters", dest="max_clusters", type=int, default=30,
        help="Cap clusters processed (default: %(default)s).",
    )
    p_gap.add_argument(
        "--top-gaps-per-cluster", dest="top_gaps_per_cluster", type=int, default=3,
        help="Max gap candidates per cluster (default: %(default)s).",
    )
    p_gap.add_argument(
        "--sample", type=int, default=None,
        help="Cap generator calls to the first N clusters (default: no cap).",
    )
    p_gap.add_argument(
        "--seed", type=int, default=42,
        help="K-means random_state for deterministic clusters (default: %(default)s).",
    )
    p_gap.add_argument(
        "--json", action="store_true",
        help="Emit JSON instead of markdown (schema_version: 1).",
    )
    p_gap.set_defaults(func=_cmd_gap)

    # answer (P6)
    p_answer = sub.add_parser(
        "answer",
        help="Draft stub notes that answer the gaps found by `wikilens gap`.",
    )
    p_answer.add_argument("vault_path", type=Path)
    p_answer.add_argument(
        "--gaps",
        required=True,
        type=Path,
        help="Path to a `wikilens gap --json` output file (required).",
    )
    p_answer.add_argument(
        "--db", default=DEFAULT_DB_PATH, help="Store path (default: %(default)s)"
    )
    p_answer.add_argument(
        "--judge",
        choices=["none", "openai", "claude"],
        default="openai",
        help=(
            "Drafter backend. 'openai' uses OpenAIDrafter (default); "
            "'claude' uses ClaudeDrafter; 'none' uses MockDrafter (no LLM calls)."
        ),
    )
    p_answer.add_argument(
        "--model",
        default="gpt-4o",
        help="Model for --judge openai/claude (default: %(default)s).",
    )
    p_answer.add_argument(
        "--top-k", dest="top_k", type=int, default=8,
        help="Retrieval neighbors per gap (default: %(default)s).",
    )
    p_answer.add_argument(
        "--retrieval-mode", dest="retrieval_mode",
        choices=["dense", "bm25", "hybrid", "rerank"],
        default="rerank",
        help="Retrieval strategy (default: %(default)s).",
    )
    p_answer.add_argument(
        "--min-supporting", dest="min_supporting", type=int, default=2,
        help="Skip gap if retrieved chunks < N; emit external-research stub (default: %(default)s).",
    )
    p_answer.add_argument(
        "--sample", type=int, default=None,
        help="Cap total drafts produced (smoke mode).",
    )
    p_answer.add_argument(
        "--write", action="store_true",
        help="Write stubs to disk. Requires --out.",
    )
    p_answer.add_argument(
        "--out", default=None,
        help="Output directory for --write (required when --write is set).",
    )
    p_answer.add_argument(
        "--json", action="store_true",
        help="Emit JSON report instead of markdown (schema_version: 1).",
    )
    p_answer.set_defaults(func=_cmd_answer)

    # Stubs for later phases (keep the help surface honest)
    for name, phase in [
        ("benchmark", "P7"),
    ]:
        p = sub.add_parser(name, help=f"({phase} — not implemented)")
        p.set_defaults(func=_cmd_stub(name, phase))

    return parser


def main(argv: list[str] | None = None) -> int:
    # On Windows, stdout defaults to cp1252 and will crash on non-Latin
    # characters that commonly appear in note content (arrows, em-dashes, etc.).
    # Force UTF-8 when we can; fall back silently on platforms without .reconfigure.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

    parser = _build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
