"""P5 eval harness — Gap Generator quality against human-gold gap labels.

Two-stage evaluation:

1. **Cluster-stage recall**: does the pipeline produce *any* gap candidate
   (across all clusters) that a ClaudeMatcher would score >= threshold for
   each gold gap? Measures clustering + generation quality independently of
   the matcher.

2. **Matcher-stage P/R/F1**: after best-matching each proposal to a gold
   gap, compute Precision, Recall, and F1. A proposal is a True Positive iff
   it matches (score >= threshold) to a gold gap that hasn't been claimed yet.
   Reports per run; appends a timestamped section to BENCHMARK.md.

3. **Borderline-decision log**: every matcher call with score 3 or 4 is
   written to docs/p5-matcher-notes.md for human review (Step 16 of the SDD).

Usage:
    # dry-run (MockGenerator + SubstringMatcher, no API calls):
    python scripts/eval_p5.py --judge none

    # full eval with Claude:
    python scripts/eval_p5.py --judge claude

    # sample first N clusters (quick smoke):
    python scripts/eval_p5.py --judge claude --sample 5

Outputs:
    - Two-stage metrics table to stdout.
    - Timestamped section appended to BENCHMARK.md.
    - Borderline matcher decisions appended to docs/p5-matcher-notes.md.

Exit code: 0 if F1 >= 0.60 on labeled gaps (or --judge none), else 1.
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
VAULT_DEFAULT = REPO_ROOT / "fixtures" / "gaps_vault"
TRUTH_DEFAULT = REPO_ROOT / "fixtures" / "eval" / "p5_ground_truth.json"
DB_DEFAULT = REPO_ROOT / ".wikilens_p5_eval" / "db"
BENCHMARK_DEFAULT = REPO_ROOT / "BENCHMARK.md"
MATCHER_NOTES_DEFAULT = REPO_ROOT / "docs" / "p5-matcher-notes.md"

PASS_F1_THRESHOLD = 0.60
DEFAULT_K = None        # auto (round(sqrt(n_chunks)))
DEFAULT_MIN_CLUSTER_SIZE = 3
DEFAULT_MAX_CLUSTERS = 30
DEFAULT_TOP_GAPS_PER_CLUSTER = 3


@dataclass
class MatchResult:
    """One (gold gap, proposed gap) matcher call result."""
    gap_id: str
    gold_question: str
    proposal: str
    score: int
    rationale: str

    @property
    def is_match(self) -> bool:
        from wikilens.matcher import DEFAULT_MATCH_THRESHOLD
        return self.score >= DEFAULT_MATCH_THRESHOLD

    @property
    def is_borderline(self) -> bool:
        return self.score in (3, 4)


def _git_rev() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO_ROOT, stderr=subprocess.DEVNULL, text=True,
        ).strip() or "unknown"
    except Exception:
        return "unknown"


def format_metrics_table(
    cluster_recall: float,
    n_surfaced: int,
    n_gold: int,
    tp: int,
    fp: int,
    fn: int,
) -> str:
    prec = tp / (tp + fp) if (tp + fp) else 1.0
    rec  = tp / (tp + fn) if (tp + fn) else 1.0
    f1   = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    lines = [
        f"Cluster-stage recall: {n_surfaced}/{n_gold} = {cluster_recall:.2f}",
        "",
        "| Stage        | TP | FP | FN | Precision | Recall | F1   |",
        "|--------------|----|----|----|-----------|--------|------|",
        f"| matcher      | {tp:>2} | {fp:>2} | {fn:>2} "
        f"| {prec:>9.2f} | {rec:>6.2f} | {f1:>4.2f} |",
    ]
    return "\n".join(lines)


def write_benchmark_md(
    table: str,
    vault: Path,
    chunks: int,
    n_clusters: int,
    n_proposals: int,
    n_gold: int,
    generator_name: str,
    matcher_name: str,
    elapsed_s: float,
    path: Path,
) -> None:
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    section = (
        f"\n## {timestamp} — P5 eval ({_git_rev()})\n\n"
        f"- Vault: `{vault.as_posix()}` ({chunks} chunks, {n_clusters} clusters).\n"
        f"- Generator: `{generator_name}`. Gap proposals: {n_proposals}. "
        f"Gold gaps: {n_gold}.\n"
        f"- Matcher: `{matcher_name}` (threshold ≥ 4/5).\n"
        f"- Wall clock: {elapsed_s:.1f}s.\n\n"
        f"{table}\n"
    )
    header_additions = (
        "- **Gap generator** (`fixtures/gaps_vault/` + "
        "`fixtures/eval/p5_ground_truth.json`):\n"
        "  ```\n"
        "  wikilens ingest fixtures/gaps_vault --db .wikilens_p5_eval/db\n"
        "  python scripts/eval_p5.py --judge claude\n"
        "  ```\n"
    )
    if path.exists():
        prior = path.read_text(encoding="utf-8")
        # Insert the gap generator entry into the header reproducer list.
        anchor = "Each harness **appends**"
        if anchor in prior and "eval_p5.py" not in prior:
            prior = prior.replace(
                anchor, header_additions + "\n" + anchor, 1
            )
        marker = "\n## "
        idx = prior.find(marker)
        preamble = prior[:idx] if idx >= 0 else prior
        body = prior[idx:] if idx >= 0 else ""
        path.write_text(preamble + section + body, encoding="utf-8")
    else:
        path.write_text(section, encoding="utf-8")


def write_matcher_notes(
    borderline: list[MatchResult],
    path: Path,
    run_ts: str,
    git_rev: str,
) -> None:
    """Append borderline decisions to docs/p5-matcher-notes.md."""
    if not borderline:
        return
    lines = [f"\n## {run_ts} ({git_rev}) — {len(borderline)} borderline decision(s)\n"]
    for r in borderline:
        lines.append(f"### gap_id: `{r.gap_id}` — score {r.score}")
        lines.append(f"- **Gold:** {r.gold_question}")
        lines.append(f"- **Proposed:** {r.proposal}")
        lines.append(f"- **Rationale:** {r.rationale}")
        lines.append("")
    content = "\n".join(lines)
    if path.exists():
        path.write_text(path.read_text(encoding="utf-8") + content, encoding="utf-8")
    else:
        header = (
            "# P5 Matcher Borderline Decisions\n\n"
            "Decisions where score was 3 or 4 (borderline zone). "
            "Reviewed after each eval run to assess rubric quality.\n"
        )
        path.write_text(header + content, encoding="utf-8")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--vault", type=Path, default=VAULT_DEFAULT)
    p.add_argument("--db", type=Path, default=DB_DEFAULT)
    p.add_argument("--truth", type=Path, default=TRUTH_DEFAULT)
    p.add_argument(
        "--judge", choices=["none", "claude"], default="claude",
        help="Generator + matcher backend. 'none' uses mocks.",
    )
    p.add_argument("--model", default="claude-sonnet-4-6")
    p.add_argument("--sample", type=int, default=None,
                   help="Cap generator to first N clusters.")
    p.add_argument("--k", type=int, default=DEFAULT_K)
    p.add_argument("--min-cluster-size", dest="min_cluster_size",
                   type=int, default=DEFAULT_MIN_CLUSTER_SIZE)
    p.add_argument("--max-clusters", dest="max_clusters",
                   type=int, default=DEFAULT_MAX_CLUSTERS)
    p.add_argument("--top-gaps-per-cluster", dest="top_gaps_per_cluster",
                   type=int, default=DEFAULT_TOP_GAPS_PER_CLUSTER)
    p.add_argument("--benchmark", type=Path, default=BENCHMARK_DEFAULT)
    p.add_argument("--matcher-notes", type=Path, default=MATCHER_NOTES_DEFAULT)
    args = p.parse_args()

    import contextlib
    with contextlib.suppress(AttributeError, OSError):
        sys.stdout.reconfigure(encoding="utf-8")

    # --- Load ground truth -----------------------------------------------
    truth_path = args.truth.resolve()
    if not truth_path.exists():
        print(f"ERROR: ground truth not found: {truth_path}", file=sys.stderr)
        return 1
    gt = json.loads(truth_path.read_text(encoding="utf-8"))
    gold_gaps: list[dict] = gt["gaps"]
    print(f"[truth] {len(gold_gaps)} gold gaps loaded from {truth_path.name}")

    # --- Ingest ----------------------------------------------------------
    from wikilens.embed import BGEEmbedder
    from wikilens.pipeline import ingest_vault
    from wikilens.store import LanceDBStore

    print(f"[ingest] {args.vault}")
    embedder = BGEEmbedder()
    ingest_vault(vault_root=args.vault, db_path=str(args.db), embedder=embedder)
    store = LanceDBStore(db_path=str(args.db), dim=embedder.dim)
    chunks_total = store.count()

    # --- Generator -------------------------------------------------------
    from wikilens.gap import generate_gaps
    from wikilens.generator import Generator

    if args.judge == "none":
        from wikilens.generator import MockGenerator
        generator: Generator = MockGenerator()
    else:
        from wikilens.generator import ClaudeGenerator
        try:
            generator = ClaudeGenerator(model=args.model)
        except (OSError, ImportError) as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 1

    print(f"[generate] clustering + proposing gaps (generator: {generator.name}) …")
    t0 = time.perf_counter()
    clusters, findings = generate_gaps(
        store,
        generator,
        k=args.k,
        min_cluster_size=args.min_cluster_size,
        max_clusters=args.max_clusters,
        top_gaps_per_cluster=args.top_gaps_per_cluster,
        sample=args.sample,
    )
    t_gen = time.perf_counter() - t0
    proposals = [f.candidate.gap_question for f in findings]
    print(
        f"  {len(clusters)} clusters → {len(findings)} gap proposals in {t_gen:.2f}s"
    )

    # --- Matcher ---------------------------------------------------------
    from wikilens.matcher import DEFAULT_MATCH_THRESHOLD, Matcher

    if args.judge == "none":
        from wikilens.matcher import SubstringMatcher
        matcher: Matcher = SubstringMatcher()
    else:
        from wikilens.matcher import ClaudeMatcher
        try:
            matcher = ClaudeMatcher(model=args.model)
        except (OSError, ImportError) as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 1

    print(
        f"[match] scoring {len(gold_gaps)} gold × {len(proposals)} proposals "
        f"(matcher: {matcher.name}, threshold: {DEFAULT_MATCH_THRESHOLD}) …"
    )

    # Strategy: for each proposal, find its best gold-gap match.
    # A proposal is a TP only if its best match is >= threshold AND that
    # gold gap hasn't been claimed by a higher-scoring proposal.
    # A gold gap is a FN if no proposal matched it.

    t_match_start = time.perf_counter()
    all_match_results: list[MatchResult] = []

    # Build a score matrix: scores[p_idx][g_idx] = MatchResult
    score_matrix: list[list[MatchResult]] = []
    for p_idx, proposal in enumerate(proposals):
        row: list[MatchResult] = []
        for g in gold_gaps:
            verdict = matcher.score_pair(g["gold_question"], proposal)
            mr = MatchResult(
                gap_id=g["gap_id"],
                gold_question=g["gold_question"],
                proposal=proposal,
                score=verdict.score,
                rationale=verdict.rationale,
            )
            row.append(mr)
            all_match_results.append(mr)
        score_matrix.append(row)
        print(
            f"  proposal {p_idx + 1:>3}/{len(proposals)}: "
            f"{proposal[:70]!r}"
        )

    t_match = time.perf_counter() - t_match_start
    elapsed_total = t_gen + t_match

    # ---- Cluster-stage recall -------------------------------------------
    # For each gold gap, is there at least one proposal that scores >= threshold?
    gold_surfaced = set()
    for g_idx, g in enumerate(gold_gaps):
        for p_row in score_matrix:
            if p_row[g_idx].score >= DEFAULT_MATCH_THRESHOLD:
                gold_surfaced.add(g["gap_id"])
                break
    cluster_recall = len(gold_surfaced) / len(gold_gaps) if gold_gaps else 1.0

    # ---- Greedy best-match assignment (P/R/F1) --------------------------
    # For each proposal (in order), claim the gold gap with the highest score
    # if that score >= threshold. Each gold gap can only be claimed once.
    claimed_gold: set[str] = set()
    tp = 0
    fp = 0

    for p_idx in range(len(proposals)):
        best_score = -1
        best_g_idx = -1
        for g_idx, g in enumerate(gold_gaps):
            if g["gap_id"] in claimed_gold:
                continue
            s = score_matrix[p_idx][g_idx].score
            if s > best_score:
                best_score = s
                best_g_idx = g_idx
        if best_score >= DEFAULT_MATCH_THRESHOLD and best_g_idx >= 0:
            tp += 1
            claimed_gold.add(gold_gaps[best_g_idx]["gap_id"])
        else:
            fp += 1

    fn = len(gold_gaps) - len(claimed_gold)

    print(f"\n[timing] generation {t_gen:.1f}s  matching {t_match:.1f}s  "
          f"total {elapsed_total:.1f}s")

    # ---- Metrics --------------------------------------------------------
    table = format_metrics_table(cluster_recall, len(gold_surfaced), len(gold_gaps),
                                 tp, fp, fn)
    print()
    print(table)

    prec = tp / (tp + fp) if (tp + fp) else 1.0
    rec  = tp / (tp + fn) if (tp + fn) else 1.0
    f1   = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0

    if hasattr(matcher, "abstentions") and matcher.abstentions:
        print(f"Matcher abstentions: {matcher.abstentions}")
    if hasattr(generator, "abstentions") and generator.abstentions:
        print(f"Generator abstentions: {generator.abstentions}")

    passed = args.judge == "none" or f1 >= PASS_F1_THRESHOLD
    status = "PASS" if passed else "FAIL"
    print(f"\n[{status}] overall F1 = {f1:.2f}  (threshold: {PASS_F1_THRESHOLD})")

    # ---- Borderline decision log ----------------------------------------
    borderline = [r for r in all_match_results if r.is_borderline]
    if borderline:
        run_ts = time.strftime("%Y-%m-%d %H:%M:%S")
        write_matcher_notes(borderline, args.matcher_notes, run_ts, _git_rev())
        print(f"wrote {len(borderline)} borderline decisions to {args.matcher_notes}")

    # ---- BENCHMARK.md ---------------------------------------------------
    write_benchmark_md(
        table=table,
        vault=args.vault,
        chunks=chunks_total,
        n_clusters=len(clusters),
        n_proposals=len(findings),
        n_gold=len(gold_gaps),
        generator_name=generator.name,
        matcher_name=matcher.name,
        elapsed_s=elapsed_total,
        path=args.benchmark,
    )
    print(f"wrote {args.benchmark}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
