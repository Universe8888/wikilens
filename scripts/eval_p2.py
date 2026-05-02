"""P2 eval harness — compute recall@5 across four retrieval modes and write an
ablation table to BENCHMARK.md.

Usage:
    python scripts/eval_p2.py \\
        --vault fixtures/sample_vault \\
        --queries fixtures/eval/p2_queries.jsonl \\
        --db .wikilens_test/db

Assumes the vault has already been ingested into `--db`. Pass `--reingest` to
rebuild first.

Outputs:
    - Human-readable ablation table to stdout.
    - Appends the table + a timestamp header to BENCHMARK.md (top of file).
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from wikilens.embed import BGEEmbedder
from wikilens.query import Mode, query
from wikilens.rerank import BGEReranker
from wikilens.store import LanceDBStore

MODES: tuple[Mode, ...] = ("dense", "bm25", "hybrid", "rerank")
REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class QueryRow:
    id: str
    difficulty: str
    query: str
    expected_titles: list[str]


def load_queries(path: Path) -> list[QueryRow]:
    rows: list[QueryRow] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        rows.append(
            QueryRow(
                id=d["id"],
                difficulty=d.get("difficulty", "unknown"),
                query=d["query"],
                expected_titles=list(d["expected_titles"]),
            )
        )
    return rows


def recall_at_k(result_titles: list[str], expected: list[str], k: int = 5) -> float:
    """Fraction of expected titles that appear in the first k results.

    For a strict recall@5 over a single expected title this is either 0 or 1.
    When multiple expected titles are listed, we reward partial hits — e.g. 2
    out of 3 expected = 0.67 — but the eval metric reports the hit rate
    (≥1 match) by default, not partial recall.
    """
    top_k = set(result_titles[:k])
    hits = sum(1 for t in expected if t in top_k)
    return hits / len(expected)


def hit_at_k(result_titles: list[str], expected: list[str], k: int = 5) -> int:
    """1 if any expected title appears in top-k, else 0."""
    top_k = set(result_titles[:k])
    return 1 if any(t in top_k for t in expected) else 0


@dataclass
class ModeReport:
    mode: str
    hit_rate_at_5: float
    partial_recall_at_5: float
    hit_rate_easy: float
    hit_rate_medium: float
    hit_rate_hard: float
    latency_p50_ms: float
    latency_p95_ms: float
    latency_mean_ms: float
    failures: list[str]  # query ids where hit@5 was 0


def run_mode(
    mode: Mode,
    rows: list[QueryRow],
    store: LanceDBStore,
    embedder: BGEEmbedder,
    reranker: BGEReranker | None,
    k: int = 5,
) -> ModeReport:
    latencies: list[float] = []
    hits: list[int] = []
    recalls: list[float] = []
    per_difficulty_hits: dict[str, list[int]] = {"easy": [], "medium": [], "hard": []}
    failures: list[str] = []

    for row in rows:
        t0 = time.perf_counter()
        results = query(
            row.query,
            store=store,
            embedder=embedder,
            mode=mode,
            k=k,
            reranker=reranker if mode == "rerank" else None,
        )
        dt_ms = (time.perf_counter() - t0) * 1000.0
        latencies.append(dt_ms)
        titles = [r.source_rel for r in results]

        h = hit_at_k(titles, row.expected_titles, k=k)
        r = recall_at_k(titles, row.expected_titles, k=k)
        hits.append(h)
        recalls.append(r)
        if row.difficulty in per_difficulty_hits:
            per_difficulty_hits[row.difficulty].append(h)
        if h == 0:
            failures.append(row.id)

    def _pct(xs: list[int]) -> float:
        return sum(xs) / len(xs) if xs else 0.0

    return ModeReport(
        mode=mode,
        hit_rate_at_5=_pct(hits),
        partial_recall_at_5=statistics.mean(recalls) if recalls else 0.0,
        hit_rate_easy=_pct(per_difficulty_hits["easy"]),
        hit_rate_medium=_pct(per_difficulty_hits["medium"]),
        hit_rate_hard=_pct(per_difficulty_hits["hard"]),
        latency_p50_ms=statistics.median(latencies) if latencies else 0.0,
        latency_p95_ms=_percentile(latencies, 95) if latencies else 0.0,
        latency_mean_ms=statistics.mean(latencies) if latencies else 0.0,
        failures=failures,
    )


def _percentile(data: list[float], pct: float) -> float:
    """Simple nearest-rank percentile (no interpolation)."""
    if not data:
        return 0.0
    s = sorted(data)
    k = max(0, min(len(s) - 1, int(round((pct / 100.0) * (len(s) - 1)))))
    return s[k]


def format_table(reports: list[ModeReport], n_queries: int) -> str:
    lines = [
        "| Mode | Hit@5 | Recall@5 | Easy | Medium | Hard | p50 (ms) | p95 (ms) | mean (ms) |",
        "|------|-------|----------|------|--------|------|----------|----------|-----------|",
    ]
    for r in reports:
        lines.append(
            f"| `{r.mode}` "
            f"| {r.hit_rate_at_5:.2f} "
            f"| {r.partial_recall_at_5:.2f} "
            f"| {r.hit_rate_easy:.2f} "
            f"| {r.hit_rate_medium:.2f} "
            f"| {r.hit_rate_hard:.2f} "
            f"| {r.latency_p50_ms:.0f} "
            f"| {r.latency_p95_ms:.0f} "
            f"| {r.latency_mean_ms:.0f} |"
        )
    lines.append("")
    lines.append(f"Eval set: {n_queries} queries.")
    return "\n".join(lines)


def _git_rev() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO_ROOT,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        return out or "unknown"
    except Exception:
        return "unknown"


def write_benchmark_md(
    reports: list[ModeReport],
    table: str,
    n_queries: int,
    chunk_count: int,
    path: Path,
) -> None:
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    header = (
        "# Benchmark\n\n"
        "Honest numbers across the project's eval suites. Every run is "
        "reproducible from a fresh clone.\n\n"
        "- **Retrieval** (`fixtures/sample_vault/` + `fixtures/eval/p2_queries.jsonl`):\n"
        "  ```\n"
        "  wikilens ingest fixtures/sample_vault && python scripts/eval_p2.py\n"
        "  ```\n"
        "- **Link audit** (`fixtures/audit_vault/` + "
        "`fixtures/eval/p3_ground_truth.json`):\n"
        "  ```\n"
        "  python scripts/eval_p3.py\n"
        "  ```\n\n"
        "Each harness **appends** a timestamped section below; prior runs are "
        "preserved so regressions are visible side-by-side.\n"
    )
    section = (
        f"\n## {timestamp} — P2 eval ({_git_rev()})\n\n"
        f"- Corpus: {chunk_count} chunks across the sample vault.\n"
        f"- Eval: {n_queries} hand-written queries, mixed easy/medium/hard.\n"
        f"- Hardware: developer laptop, CPU-only (no GPU).\n\n"
        f"{table}\n"
    )
    # Failures for the best mode (by hit@5) help diagnose where retrieval breaks down.
    best = max(reports, key=lambda r: r.hit_rate_at_5)
    if best.failures:
        section += (
            f"\n**{best.mode} mode failures (hit@5 = 0):** "
            f"{', '.join(best.failures)}\n"
        )
    if path.exists():
        prior = path.read_text(encoding="utf-8")
        if prior.startswith("# Benchmark"):
            # Replace the existing header prose with the canonical one, then
            # prepend the new section above the prior dated sections. The
            # first `\n## ` is the boundary between header and dated body.
            marker = "\n## "
            idx = prior.find(marker)
            body = prior[idx:] if idx >= 0 else ""
            path.write_text(header + section + body, encoding="utf-8")
        else:
            path.write_text(header + section + "\n" + prior, encoding="utf-8")
    else:
        path.write_text(header + section, encoding="utf-8")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--vault", type=Path, default=Path("fixtures/sample_vault"))
    p.add_argument("--queries", type=Path, default=Path("fixtures/eval/p2_queries.jsonl"))
    p.add_argument("--db", type=Path, default=Path(".wikilens_test/db"))
    p.add_argument("--benchmark", type=Path, default=Path("BENCHMARK.md"))
    p.add_argument("--reingest", action="store_true", help="Rebuild the index first.")
    p.add_argument(
        "--warmup", action="store_true",
        help="Run each query once before measuring (amortizes first-call model init).",
    )
    args = p.parse_args()

    from contextlib import suppress

    with suppress(AttributeError, OSError):
        sys.stdout.reconfigure(encoding="utf-8")

    if args.reingest:
        from wikilens.pipeline import ingest_vault
        print(f"[reingest] {args.vault} → {args.db}")
        report = ingest_vault(vault_root=args.vault, db_path=str(args.db))
        print(report.summary())

    rows = load_queries(args.queries)
    print(f"loaded {len(rows)} queries from {args.queries}")

    embedder = BGEEmbedder()
    store = LanceDBStore(db_path=str(args.db), dim=embedder.dim)
    chunk_count = store.count()
    if chunk_count == 0:
        print(f"ERROR: no chunks indexed at {args.db}. Run with --reingest.", file=sys.stderr)
        return 2
    print(f"store: {chunk_count} chunks indexed")

    reranker = BGEReranker()

    if args.warmup:
        print("[warmup] running each mode once on q01 to prime model caches")
        for m in MODES:
            query(
                rows[0].query, store=store, embedder=embedder, mode=m,
                reranker=reranker if m == "rerank" else None, k=5,
            )

    reports: list[ModeReport] = []
    for m in MODES:
        print(f"[run] {m}")
        rep = run_mode(m, rows, store, embedder, reranker, k=5)
        print(
            f"  hit@5={rep.hit_rate_at_5:.2f}  recall@5={rep.partial_recall_at_5:.2f}  "
            f"p50={rep.latency_p50_ms:.0f}ms  p95={rep.latency_p95_ms:.0f}ms"
        )
        reports.append(rep)

    table = format_table(reports, n_queries=len(rows))
    print()
    print(table)

    write_benchmark_md(
        reports=reports,
        table=table,
        n_queries=len(rows),
        chunk_count=chunk_count,
        path=args.benchmark,
    )
    print(f"\nwrote {args.benchmark}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
