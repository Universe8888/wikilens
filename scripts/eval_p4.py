"""P4 eval harness — judge agreement with human-gold contradiction labels.

Runs `generate_candidate_pairs` over fixtures/contradictions_vault, then
calls the judge on every pair whose IDs appear in p4_ground_truth.json,
and computes Precision / Recall / F1 of the judge vs. the gold labels.

Usage:
    # dry-run (MockJudge, no API calls):
    python scripts/eval_p4.py --judge none

    # full eval with Claude:
    python scripts/eval_p4.py --judge claude

    # sample the first N gold pairs (quick smoke):
    python scripts/eval_p4.py --judge claude --sample 5

Outputs:
    - P/R/F1 table per contradiction class to stdout.
    - Appends a timestamped section to BENCHMARK.md.

Exit code: 0 if F1 >= 0.75 on labeled pairs (or --judge none), else 1.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VAULT_DEFAULT = REPO_ROOT / "fixtures" / "contradictions_vault"
TRUTH_DEFAULT = REPO_ROOT / "fixtures" / "eval" / "p4_ground_truth.json"
DB_DEFAULT = REPO_ROOT / ".wikilens_p4_eval" / "db"
BENCHMARK_DEFAULT = REPO_ROOT / "BENCHMARK.md"

PASS_F1_THRESHOLD = 0.75


@dataclass
class ClassReport:
    name: str
    tp: int
    fp: int
    fn: int

    @property
    def precision(self) -> float:
        denom = self.tp + self.fp
        return self.tp / denom if denom else 1.0

    @property
    def recall(self) -> float:
        denom = self.tp + self.fn
        return self.tp / denom if denom else 1.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return (2 * p * r / (p + r)) if (p + r) else 0.0


def format_table(reports: list[ClassReport]) -> str:
    lines = [
        "| Class    | TP | FP | FN | Precision | Recall | F1   |",
        "|----------|----|----|----|-----------|--------|------|",
    ]
    for r in reports:
        lines.append(
            f"| {r.name:<8} "
            f"| {r.tp:>2} | {r.fp:>2} | {r.fn:>2} "
            f"| {r.precision:>9.2f} "
            f"| {r.recall:>6.2f} "
            f"| {r.f1:>4.2f} |"
        )
    return "\n".join(lines)


def _git_rev() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO_ROOT, stderr=subprocess.DEVNULL, text=True,
        ).strip() or "unknown"
    except Exception:
        return "unknown"


def write_benchmark_md(
    reports: list[ClassReport],
    table: str,
    vault: Path,
    chunks: int,
    candidates: int,
    judged: int,
    judge_name: str,
    elapsed_s: float,
    path: Path,
) -> None:
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    section = (
        f"\n## {timestamp} — P4 eval ({_git_rev()})\n\n"
        f"- Vault: `{vault.as_posix()}` ({chunks} chunks, {candidates} candidate pairs).\n"
        f"- Judge: `{judge_name}`. Labeled pairs judged: {judged}.\n"
        f"- Wall clock: {elapsed_s:.1f}s.\n\n"
        f"{table}\n"
    )
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
        "  ```\n"
        "- **Contradiction finder** (`fixtures/contradictions_vault/` + "
        "`fixtures/eval/p4_ground_truth.json`):\n"
        "  ```\n"
        "  wikilens ingest fixtures/contradictions_vault --db .wikilens_p4_eval/db\n"
        "  python scripts/eval_p4.py --judge claude\n"
        "  ```\n\n"
        "Each harness **appends** a timestamped section below; prior runs are "
        "preserved so regressions are visible side-by-side.\n"
    )
    if path.exists():
        prior = path.read_text(encoding="utf-8")
        if prior.startswith("# Benchmark"):
            marker = "\n## "
            idx = prior.find(marker)
            body = prior[idx:] if idx >= 0 else ""
            path.write_text(header + section + body, encoding="utf-8")
        else:
            path.write_text(header + section + "\n" + prior, encoding="utf-8")
    else:
        path.write_text(header + section, encoding="utf-8")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--vault", type=Path, default=VAULT_DEFAULT)
    p.add_argument("--db", type=Path, default=DB_DEFAULT)
    p.add_argument(
        "--truth", type=Path, default=TRUTH_DEFAULT,
        help="Path to p4_ground_truth.json",
    )
    p.add_argument(
        "--judge", choices=["none", "claude"], default="claude",
        help="Judge backend (default: claude). 'none' uses MockJudge.",
    )
    p.add_argument(
        "--model", default="claude-sonnet-4-6",
        help="Model for --judge claude (default: %(default)s).",
    )
    p.add_argument(
        "--sample", type=int, default=None,
        help="Limit judge calls to first N gold pairs (default: all).",
    )
    p.add_argument("--benchmark", type=Path, default=BENCHMARK_DEFAULT)
    args = p.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

    # --- Load ground truth -----------------------------------------------
    truth_path = args.truth.resolve()
    if not truth_path.exists():
        print(f"ERROR: ground truth not found: {truth_path}", file=sys.stderr)
        return 1
    gt = json.loads(truth_path.read_text(encoding="utf-8"))
    gold_pairs: list[dict] = gt["pairs"]
    gold_by_key: dict[frozenset, dict] = {
        frozenset([p["chunk_a_id"], p["chunk_b_id"]]): p for p in gold_pairs
    }
    if args.sample is not None:
        gold_pairs = gold_pairs[: args.sample]

    # --- Ingest (if needed) + pair gen -----------------------------------
    from wikilens.embed import BGEEmbedder
    from wikilens.pipeline import ingest_vault
    from wikilens.store import LanceDBStore

    print(f"[ingest] {args.vault}")
    embedder = BGEEmbedder()
    ingest_vault(vault_root=args.vault, db_path=str(args.db), embedder=embedder)
    store = LanceDBStore(db_path=str(args.db), dim=embedder.dim)
    chunks_total = store.count()

    print("[pair-gen] building candidate pairs via hybrid retrieval …")
    from wikilens.contradict import generate_candidate_pairs
    t0 = time.perf_counter()
    pairs = generate_candidate_pairs(store, embedder=embedder)
    t_pair = time.perf_counter() - t0
    print(f"  {len(pairs)} candidate pairs in {t_pair:.2f}s")

    # Index pairs by their chunk-ID frozenset for O(1) lookup.
    pair_by_key: dict[frozenset, object] = {
        frozenset([p.a.chunk_id, p.b.chunk_id]): p for p in pairs
    }

    # --- Judge -----------------------------------------------------------
    from wikilens.judge import ClaudeJudge, JudgeVerdict, MockJudge

    if args.judge == "none":
        judge = MockJudge()
    else:
        try:
            judge = ClaudeJudge(model=args.model)
        except (EnvironmentError, ImportError) as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 1

    print(f"[judge] {judge.name} — evaluating {len(gold_pairs)} labeled pairs …")

    # For each gold pair, either look it up in generated candidates (expected
    # path when retrieval-based pair gen is working) or synthesize a pair
    # from the chunk texts directly (fallback for the eval harness so we can
    # still score the judge even when a pair didn't surface via retrieval).
    from wikilens.contradict import CandidatePair, ChunkRef

    table_rows = store._get_or_create_table().to_arrow().to_pylist()  # type: ignore[attr-defined]
    chunk_by_id: dict[str, dict] = {r["chunk_id"]: r for r in table_rows}

    judged = 0
    results: list[tuple[dict, JudgeVerdict]] = []
    t_judge_start = time.perf_counter()

    for gp in gold_pairs:
        key = frozenset([gp["chunk_a_id"], gp["chunk_b_id"]])
        candidate = pair_by_key.get(key)
        if candidate is None:
            # Pair not surfaced by retrieval — synthesize from store.
            ra = chunk_by_id.get(gp["chunk_a_id"])
            rb = chunk_by_id.get(gp["chunk_b_id"])
            if ra is None or rb is None:
                print(f"  WARN: chunk ID not found in store for pair {gp['pair_id']!r}")
                continue
            text_a = ra["text"]
            text_b = rb["text"]
        else:
            text_a = candidate.a.text  # type: ignore[union-attr]
            text_b = candidate.b.text  # type: ignore[union-attr]

        verdict = judge.score_pair(text_a, text_b)
        results.append((gp, verdict))
        judged += 1
        print(
            f"  [{judged:3d}/{len(gold_pairs)}] {gp['pair_id']:40s}  "
            f"judge={verdict.verdict!s:5s} ({verdict.type}, {verdict.score:.2f})  "
            f"gold={gp['gold_verdict']!s:5s}"
        )

    t_judge = time.perf_counter() - t_judge_start
    elapsed_total = t_pair + t_judge
    print(f"\n[timing] pair-gen {t_pair:.1f}s  judging {t_judge:.1f}s  total {elapsed_total:.1f}s")

    # --- Compute P/R/F1 per class ----------------------------------------
    # A verdict is a TP if judge says True and gold says True AND types agree.
    # FP: judge says True, gold says False (or type mismatch).
    # FN: judge says False, gold says True.
    # We report per-class (factual, temporal) AND aggregate.

    stats: dict[str, dict[str, int]] = {
        "factual":  {"tp": 0, "fp": 0, "fn": 0},
        "temporal": {"tp": 0, "fp": 0, "fn": 0},
        "overall":  {"tp": 0, "fp": 0, "fn": 0},
    }

    for gp, verdict in results:
        gold_verdict = gp["gold_verdict"]
        gold_label = gp["label"]  # factual | temporal | none

        predicted_positive = verdict.verdict
        actual_positive = gold_verdict

        if actual_positive:
            if predicted_positive and verdict.type == gold_label:
                stats[gold_label]["tp"] += 1
                stats["overall"]["tp"] += 1
            else:
                # Judge missed it or got the type wrong.
                stats[gold_label]["fn"] += 1
                stats["overall"]["fn"] += 1
        else:
            if predicted_positive:
                # Judge said contradiction, gold says no.
                pred_class = verdict.type if verdict.type != "none" else "overall"
                if pred_class in stats:
                    stats[pred_class]["fp"] += 1
                stats["overall"]["fp"] += 1

    reports = [
        ClassReport(
            name=cls,
            tp=stats[cls]["tp"],
            fp=stats[cls]["fp"],
            fn=stats[cls]["fn"],
        )
        for cls in ("factual", "temporal", "overall")
    ]

    table = format_table(reports)
    print()
    print(table)

    # Retrieval recall: fraction of gold positive pairs that appeared in
    # generated candidates (measures pair-gen recall independently of judge).
    gold_positive_keys = {
        frozenset([p["chunk_a_id"], p["chunk_b_id"]])
        for p in gold_pairs if p["gold_verdict"]
    }
    surfaced = sum(1 for k in gold_positive_keys if k in pair_by_key)
    retrieval_recall = surfaced / len(gold_positive_keys) if gold_positive_keys else 1.0
    print(
        f"\nRetrieval recall (gold positives surfaced by pair-gen): "
        f"{surfaced}/{len(gold_positive_keys)} = {retrieval_recall:.2f}"
    )

    if hasattr(judge, "abstentions") and judge.abstentions:
        print(f"Judge abstentions (malformed JSON after retries): {judge.abstentions}")

    overall_f1 = reports[-1].f1
    passed = args.judge == "none" or overall_f1 >= PASS_F1_THRESHOLD
    status = "PASS" if passed else "FAIL"
    print(f"\n[{status}] overall F1 = {overall_f1:.2f}  (threshold: {PASS_F1_THRESHOLD})")

    write_benchmark_md(
        reports=reports,
        table=table,
        vault=args.vault,
        chunks=chunks_total,
        candidates=len(pairs),
        judged=judged,
        judge_name=judge.name,
        elapsed_s=elapsed_total,
        path=args.benchmark,
    )
    print(f"wrote {args.benchmark}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
