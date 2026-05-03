"""P9 eval harness — precision/recall of the unnamed concept detector vs. gold labels.

Ingests fixtures/concepts_vault/ into a temp LanceDB, runs the full concepts
pipeline, then scores each finding against fixtures/eval/p9_ground_truth.json.

Scoring:
  - A finding is a True Positive if its proposed_term matches the canonical gold
    term (substring overlap in either direction, case-insensitive) AND at least
    one of its supporting_notes appears in the gold concept's supporting_notes.
  - A gold concept with no matching finding is a False Negative.
  - A finding that matches no gold concept is a False Positive.

Targets (from SDD):
  Precision >= 0.70, Recall >= 0.70.

Usage:
    # dry-run (MockConceptJudge, no API calls — tests plumbing only):
    python scripts/eval_p9.py --judge none

    # full eval with OpenAI (default):
    python scripts/eval_p9.py --judge openai

    # quick smoke (cap judge calls):
    python scripts/eval_p9.py --judge openai --top-k 3

Outputs:
    - Precision/recall table to stdout.
    - Appends a timestamped section to BENCHMARK.md.

Exit code: 0 if precision >= 0.70 and recall >= 0.70 (or --judge none), else 1.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import tempfile
import time
from contextlib import redirect_stdout
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_VAULT = REPO_ROOT / "fixtures" / "concepts_vault"
TRUTH_PATH = REPO_ROOT / "fixtures" / "eval" / "p9_ground_truth.json"
BENCHMARK_PATH = REPO_ROOT / "BENCHMARK.md"

PRECISION_THRESHOLD = 0.70
RECALL_THRESHOLD = 0.70


@dataclass
class EvalResult:
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
        return 2 * p * r / (p + r) if (p + r) else 0.0


def _normalize(term: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", term.lower()).strip()


def _term_matches(proposed: str, canonical: str) -> bool:
    """True if proposed and canonical have meaningful overlap.

    Accepts if either is a substring of the other (normalized), OR if they
    share at least half their content words.
    """
    p = _normalize(proposed)
    c = _normalize(canonical)
    if c in p or p in c:
        return True
    p_words = set(p.split())
    c_words = set(c.split())
    if not c_words:
        return False
    overlap = len(p_words & c_words) / len(c_words)
    return overlap >= 0.5


def _notes_overlap(found_notes: list[str], gold_notes: list[str]) -> bool:
    found_basenames = {Path(n).name for n in found_notes}
    gold_basenames = {Path(n).name for n in gold_notes}
    return bool(found_basenames & gold_basenames)


def run_eval(
    judge: str,
    model: str,
    top_k: int,
    min_cluster_size: int,
    verbose: bool,
) -> tuple[EvalResult, dict, float]:
    from wikilens.cli import main as cli_main

    truth = json.loads(TRUTH_PATH.read_text(encoding="utf-8"))
    gold_concepts = truth["concepts"]

    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        db_path = str(tmp / "db")

        ingest_args = ["ingest", str(FIXTURE_VAULT), "--db", db_path]
        cli_main(ingest_args)

        concepts_args = [
            "concepts",
            str(FIXTURE_VAULT),
            "--db", db_path,
            "--judge", judge,
            "--model", model,
            "--top-k", str(top_k),
            "--min-cluster-size", str(min_cluster_size),
            "--json",
        ]

        buf = io.StringIO()
        t0 = time.monotonic()
        with redirect_stdout(buf):
            cli_main(concepts_args)
        elapsed = time.monotonic() - t0

        raw_json = buf.getvalue()

    report = json.loads(raw_json)
    findings = report.get("findings", [])

    if verbose:
        print(f"\nFound {len(findings)} concepts from pipeline.")

    matched_gold_ids: set[str] = set()
    fp = 0

    for finding in findings:
        proposed = finding["proposed_term"]
        found_notes = finding.get("supporting_notes", [])

        matched = False
        for gold in gold_concepts:
            if gold["id"] in matched_gold_ids:
                continue
            if _term_matches(proposed, gold["canonical_term"]) and \
               _notes_overlap(found_notes, gold["supporting_notes"]):
                matched_gold_ids.add(gold["id"])
                matched = True
                if verbose:
                    print(f"  TP: {gold['id']} (proposed={proposed!r})")
                break

        if not matched:
            fp += 1
            if verbose:
                print(f"  FP: proposed={proposed!r} notes={found_notes}")

    tp = len(matched_gold_ids)
    fn = len(gold_concepts) - tp

    if verbose:
        for gold in gold_concepts:
            if gold["id"] not in matched_gold_ids:
                print(f"  FN: {gold['id']} ({gold['canonical_term']!r}) — not surfaced")

    result = EvalResult(tp=tp, fp=fp, fn=fn)
    return result, report, elapsed


def append_benchmark(
    result: EvalResult,
    report: dict,
    elapsed: float,
    judge: str,
    model: str,
    top_k: int,
) -> None:
    ts = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M:%S")
    stats = report.get("stats", {})

    lines = [
        f"\n## {ts} — P9 eval",
        "",
        f"- Vault: `fixtures/concepts_vault` ({stats.get('total_chunks', '?')} chunks, "
        f"{stats.get('clusters_evaluated', '?')} clusters).",
        f"- Judge: `{judge}/{model}`. Top-k: {top_k}.",
        f"- Findings before filter: {stats.get('findings_before_filter', '?')}. "
        f"After filter: {len(report.get('findings', []))}.",
        f"- Wall clock: {elapsed:.1f}s.",
        "",
        "| Metric | Value | Target |",
        "|--------|-------|--------|",
        f"| TP | {result.tp} | — |",
        f"| FP | {result.fp} | — |",
        f"| FN | {result.fn} | — |",
        f"| Precision | {result.precision:.2f} | >= {PRECISION_THRESHOLD:.2f} |",
        f"| Recall | {result.recall:.2f} | >= {RECALL_THRESHOLD:.2f} |",
        f"| F1 | {result.f1:.2f} | — |",
        "",
    ]

    with open(BENCHMARK_PATH, "a", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main() -> int:
    parser = argparse.ArgumentParser(description="P9 concept detector eval harness.")
    parser.add_argument(
        "--judge",
        choices=["none", "openai", "claude"],
        default="openai",
    )
    parser.add_argument(
        "--model",
        default="gpt-4o",
    )
    parser.add_argument(
        "--top-k",
        dest="top_k",
        type=int,
        default=10,
        help="Max findings to request from the pipeline (default: 10).",
    )
    parser.add_argument(
        "--min-cluster-size",
        dest="min_cluster_size",
        type=int,
        default=2,
        help="Min cluster size passed to detector (default: 2).",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
    )
    args = parser.parse_args()

    print(
        f"P9 eval — judge={args.judge}/{args.model} "
        f"top_k={args.top_k} min_cluster_size={args.min_cluster_size}"
    )
    print("Ingesting fixture vault ...", flush=True)

    result, report, elapsed = run_eval(
        judge=args.judge,
        model=args.model,
        top_k=args.top_k,
        min_cluster_size=args.min_cluster_size,
        verbose=args.verbose,
    )

    print(f"\nResults (wall clock: {elapsed:.1f}s):")
    print(f"  TP={result.tp}  FP={result.fp}  FN={result.fn}")
    print(f"  Precision={result.precision:.2f}  Recall={result.recall:.2f}  F1={result.f1:.2f}")

    passed = args.judge == "none" or (
        result.precision >= PRECISION_THRESHOLD and result.recall >= RECALL_THRESHOLD
    )
    status = "PASS" if passed else "FAIL"
    print(f"\n  {status}  (targets: precision>={PRECISION_THRESHOLD}, recall>={RECALL_THRESHOLD})")

    append_benchmark(result, report, elapsed, args.judge, args.model, args.top_k)
    print("\nAppended results to BENCHMARK.md.")

    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
