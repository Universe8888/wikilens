"""P8 eval harness — precision/recall of the drift detector vs. gold labels.

The eval restores fixtures/drift_vault/dotgit to a live .git in a temp
directory, runs the full drift pipeline over the fixture vault, then scores
each found event against fixtures/eval/p8_ground_truth.json.

Scoring:
  - A found event is a True Positive if its note matches a gold drift event
    AND both the before_claim and after_claim semantically match (substring
    check against the gold claims — loose but avoids LLM cost here).
  - A gold drift event with no matching found event is a False Negative.
  - A found event that does not match any gold drift event is a False Positive.
  - Gold surface events that are found (incorrectly flagged) are also FPs.

Targets (from SDD):
  Precision >= 0.80, Recall >= 0.80.

Usage:
    # dry-run (MockDriftJudge, no API calls — tests plumbing only):
    python scripts/eval_p8.py --judge none

    # full eval with OpenAI (default):
    python scripts/eval_p8.py --judge openai

    # quick smoke (cap judge calls):
    python scripts/eval_p8.py --judge openai --sample 5

Outputs:
    - Precision/recall table to stdout.
    - Appends a timestamped section to BENCHMARK.md.

Exit code: 0 if precision >= 0.80 and recall >= 0.80 (or --judge none), else 1.
"""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_VAULT = REPO_ROOT / "fixtures" / "drift_vault"
TRUTH_PATH = REPO_ROOT / "fixtures" / "eval" / "p8_ground_truth.json"
BENCHMARK_PATH = REPO_ROOT / "BENCHMARK.md"

PRECISION_THRESHOLD = 0.80
RECALL_THRESHOLD = 0.80


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


def _setup_fixture_git(vault: Path, tmp: Path) -> Path:
    """Copy the vault to tmp and restore dotgit -> .git."""
    dest = tmp / "drift_vault"
    shutil.copytree(vault, dest)
    dotgit = dest / "dotgit"
    git_dir = dest / ".git"
    if dotgit.exists() and not git_dir.exists():
        dotgit.rename(git_dir)
    return dest


def _claim_matches(found_claim: str, gold_claim: str, threshold: int = 10) -> bool:
    """Loose substring match: first `threshold` chars of gold appear in found."""
    prefix = gold_claim[:threshold].lower()
    return prefix in found_claim.lower()


def run_eval(
    judge: str,
    model: str,
    sample: int | None,
    min_score: int,
    verbose: bool,
) -> tuple[EvalResult, dict, float]:
    """Run the drift pipeline and score against ground truth.

    Returns (result, raw_report_dict, wall_clock_seconds).
    """
    # Load ground truth.
    truth = json.loads(TRUTH_PATH.read_text(encoding="utf-8"))
    gold_drift = [e for e in truth["events"] if e["label"] == "drift"]

    # Set up a temp fixture dir with a live .git.
    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        vault_tmp = _setup_fixture_git(FIXTURE_VAULT, tmp)

        # Build CLI args.
        from wikilens.cli import main as cli_main

        cli_args = [
            "drift",
            str(vault_tmp),
            "--judge", judge,
            "--model", model,
            "--min-score", str(min_score),
            "--json",
        ]
        if sample is not None:
            cli_args += ["--sample", str(sample)]
        if verbose:
            cli_args.append("--verbose")

        # Capture stdout.
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        t0 = time.monotonic()
        with redirect_stdout(buf):
            cli_main(cli_args)
        elapsed = time.monotonic() - t0

        raw_json = buf.getvalue()

    report = json.loads(raw_json)
    findings = report.get("findings", [])

    if verbose:
        print(f"\nFound {len(findings)} events from drift pipeline.")

    # Score: match each finding against gold drift events.
    matched_gold_ids: set[str] = set()
    fp = 0

    for finding in findings:
        note = Path(finding["note"]).name
        before_claim = finding["before"]["claim"]
        after_claim = finding["after"]["claim"]

        matched = False
        for gold in gold_drift:
            if gold["id"] in matched_gold_ids:
                continue
            if Path(gold["note"]).name != note:
                continue
            if _claim_matches(before_claim, gold["before_claim"]) and \
               _claim_matches(after_claim, gold["after_claim"]):
                matched_gold_ids.add(gold["id"])
                matched = True
                if verbose:
                    print(f"  TP: {gold['id']} ({note})")
                break

        if not matched:
            fp += 1
            if verbose:
                print(f"  FP: {note} | {before_claim[:60]}...")

    tp = len(matched_gold_ids)
    fn = len(gold_drift) - tp

    if verbose:
        for gold in gold_drift:
            if gold["id"] not in matched_gold_ids:
                print(f"  FN: {gold['id']} ({gold['note']}) — not surfaced")

    result = EvalResult(tp=tp, fp=fp, fn=fn)
    return result, report, elapsed


def append_benchmark(
    result: EvalResult,
    report: dict,
    elapsed: float,
    judge: str,
    model: str,
    sample: int | None,
) -> None:
    ts = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M:%S")
    stats = report.get("stats", {})

    lines = [
        f"\n## {ts} — P8 eval",
        "",
        f"- Vault: `fixtures/drift_vault` ({stats.get('walked_commits', '?')} commits walked).",
        f"- Judge: `{judge}/{model}`.",
        f"- Pairs considered: {stats.get('pairs_considered', '?')}. "
        f"Filtered: {stats.get('pairs_filtered', '?')}. "
        f"Judged: {stats.get('pairs_judged', '?')}.",
        f"- Wall clock: {elapsed:.1f}s.",
        (f"- Sample cap: {sample}." if sample is not None else "- Sample cap: none."),
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
    parser = argparse.ArgumentParser(description="P8 drift detector eval harness.")
    parser.add_argument(
        "--judge",
        choices=["none", "openai", "claude"],
        default="openai",
        help="Judge backend (default: openai).",
    )
    parser.add_argument(
        "--model",
        default="gpt-4o",
        help="Model for --judge openai/claude (default: gpt-4o).",
    )
    parser.add_argument(
        "--sample",
        type=int,
        default=None,
        help="Cap judge calls to first N pairs.",
    )
    parser.add_argument(
        "--min-score",
        dest="min_score",
        type=int,
        default=4,
        help="Drift score threshold 1-5 (default: 4).",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Per-event match/miss output.",
    )
    args = parser.parse_args()

    print(
        f"P8 eval — judge={args.judge}/{args.model} "
        f"sample={args.sample} min_score={args.min_score}"
    )
    print("Setting up fixture ...", flush=True)

    result, report, elapsed = run_eval(
        judge=args.judge,
        model=args.model,
        sample=args.sample,
        min_score=args.min_score,
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

    append_benchmark(result, report, elapsed, args.judge, args.model, args.sample)
    print("\nAppended results to BENCHMARK.md.")

    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
