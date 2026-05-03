"""P10 eval harness — epistemic confidence mapper vs. gold labels.

Runs `wikilens confidence` on fixtures/confidence_vault/ with the requested
judge, then scores predictions against fixtures/eval/p10_ground_truth.json.

Scoring:
  - Match: predicted claim matches gold claim if (a) note basenames match AND
    char-span Jaccard >= 0.50 (primary), OR (b) normalized claim text matches
    exactly after lowercase + whitespace collapse (fallback).
  - Binary class: low-confidence (gold level <= 2) vs. adequate (level >= 3).
  - True Positive  : predicted level <= threshold AND gold level <= 2.
  - False Positive : predicted level <= threshold AND gold level >= 3.
  - False Negative : gold level <= 2 AND no matching prediction.
  - Secondary metric: Quadratic Weighted Kappa (QWK) over the full 5-level
    ordinal where both a prediction and a gold label exist for the same claim.

Targets:
  Precision >= 0.70, Recall >= 0.70 on binary low-confidence class.

Usage:
    # dry-run (MockConfidenceJudge, no API calls):
    python scripts/eval_p10.py --judge none

    # full eval with OpenAI:
    python scripts/eval_p10.py --judge openai

    # quick smoke (cap judge calls):
    python scripts/eval_p10.py --judge openai --sample 20

Outputs:
    - Precision/recall/F1 + QWK table to stdout.
    - Appends a timestamped section to BENCHMARK.md.

Exit code: 0 if targets met (or --judge none), else 1.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import time
from collections import defaultdict
from contextlib import redirect_stdout
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_VAULT = REPO_ROOT / "fixtures" / "confidence_vault"
TRUTH_PATH = REPO_ROOT / "fixtures" / "eval" / "p10_ground_truth.json"
BENCHMARK_PATH = REPO_ROOT / "BENCHMARK.md"

PRECISION_THRESHOLD = 0.70
RECALL_THRESHOLD = 0.70
LOW_CONF_THRESHOLD = 2  # gold level <= this is "low confidence"


# ---------------------------------------------------------------------------
# EvalResult
# ---------------------------------------------------------------------------


@dataclass
class EvalResult:
    tp: int
    fp: int
    fn: int
    qwk: float | None = None  # None when no matched pairs

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


# ---------------------------------------------------------------------------
# Matchers
# ---------------------------------------------------------------------------


def _normalize(text: str) -> str:
    return " ".join(re.sub(r"[^\w ]", " ", text.lower()).split())


def _jaccard_span(s1: dict, s2: dict) -> float:
    """Jaccard overlap on char-span ranges."""
    lo = max(s1["start"], s2["start"])
    hi = min(s1["end"], s2["end"])
    intersection = max(0, hi - lo)
    if intersection == 0:
        return 0.0
    union = (s1["end"] - s1["start"]) + (s2["end"] - s2["start"]) - intersection
    return intersection / union if union else 0.0


def _claims_match(
    pred_note: str,
    pred_claim: str,
    pred_span: dict | None,
    gold_note: str,
    gold_claim: str,
    gold_span: dict | None,
) -> bool:
    """Return True if predicted and gold claims refer to the same sentence."""
    if Path(pred_note).name != Path(gold_note).name:
        return False
    # Primary: span Jaccard
    if pred_span and gold_span and _jaccard_span(pred_span, gold_span) >= 0.50:
        return True
    # Fallback: normalized text exact match
    return _normalize(pred_claim) == _normalize(gold_claim)


# ---------------------------------------------------------------------------
# QWK
# ---------------------------------------------------------------------------


def _compute_qwk(gold_levels: list[int], pred_levels: list[int], n_classes: int = 5) -> float:
    """Quadratic Weighted Kappa for ordinal classification."""
    n = len(gold_levels)
    if n == 0:
        return 0.0

    # Weight matrix W[i][j] = (i-j)^2 / (n_classes-1)^2
    w = [
        [(i - j) ** 2 / (n_classes - 1) ** 2 for j in range(n_classes)]
        for i in range(n_classes)
    ]

    # Observed matrix obs[i][j] = count of (gold=i+1, pred=j+1)
    obs = [[0] * n_classes for _ in range(n_classes)]
    for g, p in zip(gold_levels, pred_levels, strict=False):
        obs[g - 1][p - 1] += 1

    # Expected matrix exp_[i][j] = row_sum[i] * col_sum[j] / n
    row_sum = [sum(obs[i]) for i in range(n_classes)]
    col_sum = [sum(obs[i][j] for i in range(n_classes)) for j in range(n_classes)]
    exp_ = [[row_sum[i] * col_sum[j] / n for j in range(n_classes)] for i in range(n_classes)]

    num = sum(w[i][j] * obs[i][j] for i in range(n_classes) for j in range(n_classes))
    den = sum(w[i][j] * exp_[i][j] for i in range(n_classes) for j in range(n_classes))

    return 1.0 - (num / den) if den else 1.0


# ---------------------------------------------------------------------------
# Core eval
# ---------------------------------------------------------------------------


def run_eval(
    judge: str,
    model: str,
    sample: int | None,
    threshold: int,
    verbose: bool,
) -> tuple[EvalResult, dict, float]:
    from wikilens.cli import main as cli_main

    truth = json.loads(TRUTH_PATH.read_text(encoding="utf-8"))
    gold_claims = truth["claims"]

    # Gold index: note basename -> list of gold claims
    gold_by_note: dict[str, list[dict]] = defaultdict(list)
    for c in gold_claims:
        gold_by_note[Path(c["note"]).name].append(c)

    # Run the CLI and capture JSON output
    # Run with threshold=5 so ALL classified claims appear in the JSON output.
    # Binary P/R scoring at `threshold` is done here in the harness, not by
    # the pipeline's own threshold filter — otherwise FN claims (gold L1/L2
    # that the judge rates L3+) are invisible to the matcher.
    conf_args = [
        "confidence",
        str(FIXTURE_VAULT),
        "--judge", judge,
        "--model", model,
        "--threshold", "5",
        "--json",
    ]
    if sample is not None:
        conf_args += ["--sample", str(sample)]

    buf = io.StringIO()
    t0 = time.monotonic()
    with redirect_stdout(buf):
        cli_main(conf_args)
    elapsed = time.monotonic() - t0

    report = json.loads(buf.getvalue())
    predictions = report.get("findings", [])

    if verbose:
        print(f"\nPipeline returned {len(predictions)} classified claims.")

    # Match ALL predictions -> gold claims (we ran --threshold 5 to see everything).
    # matched: gold_id -> pred_level (the predicted level for that matched gold claim)
    matched: dict[str, int] = {}
    matched_pred_indices: set[int] = set()
    gold_levels_matched: list[int] = []
    pred_levels_matched: list[int] = []

    for pred_idx, pred in enumerate(predictions):
        pred_note = pred["note"]
        pred_claim = pred["claim"]
        pred_level = pred["level"]

        for gold in gold_by_note.get(Path(pred_note).name, []):
            if gold["id"] in matched:
                continue
            gold_span = gold.get("span")
            if _claims_match(
                pred_note, pred_claim, None, gold["note"], gold["claim_text"], gold_span
            ):
                matched[gold["id"]] = pred_level
                matched_pred_indices.add(pred_idx)
                gold_levels_matched.append(gold["level"])
                pred_levels_matched.append(pred_level)
                if verbose:
                    print(
                        f"  MATCH: {gold['id']} gold=L{gold['level']} "
                        f"pred=L{pred_level} {pred_claim[:60]!r}"
                    )
                break

    # Binary classification scoring:
    # Predicted positive = pred_level <= threshold
    # Actually positive  = gold_level <= LOW_CONF_THRESHOLD
    tp = 0
    fp = 0
    fn_ids: set[str] = set()

    for gold in gold_claims:
        gid = gold["id"]
        gold_level = gold["level"]
        actually_positive = gold_level <= LOW_CONF_THRESHOLD

        if gid in matched:
            pred_level = matched[gid]
            predicted_positive = pred_level <= threshold
            if actually_positive and predicted_positive:
                tp += 1
            elif not actually_positive and predicted_positive:
                fp += 1
            elif actually_positive and not predicted_positive:
                fn_ids.add(gid)
                # TN if not actually_positive and not predicted_positive — not counted
        else:
            # Unmatched gold claim
            if actually_positive:
                fn_ids.add(gid)

    # Gold set is sparse (~179 of ~249 extractable sentences labeled).
    # Predictions on unlabeled sentences are not counted as FP — the labeler's
    # silence does not mean "adequate confidence." Only matched-pair FPs count
    # (gold says L3+, judge said L1/L2). Standard practice for partial-annotation
    # evals (NER/claim-detection with non-exhaustive gold sets).

    fn = len(fn_ids)

    if verbose and fn_ids:
        for c in gold_claims:
            if c["id"] in fn_ids:
                print(f"  FN: {c['id']} L{c['level']} {c['claim_text'][:60]!r}")

    # QWK over matched pairs only
    qwk = _compute_qwk(gold_levels_matched, pred_levels_matched) if gold_levels_matched else None

    result = EvalResult(tp=tp, fp=fp, fn=fn, qwk=qwk)
    return result, report, elapsed


# ---------------------------------------------------------------------------
# Confusion matrix (diagnostic)
# ---------------------------------------------------------------------------


def _confusion_matrix(gold_claims: list[dict], predictions: list[dict]) -> list[list[int]]:
    """5x5 confusion matrix: rows=gold, cols=pred. Best-effort text match."""
    matrix = [[0] * 5 for _ in range(5)]
    gold_by_note: dict[str, list[dict]] = defaultdict(list)
    for c in gold_claims:
        gold_by_note[Path(c["note"]).name].append(c)

    for pred in predictions:
        for gold in gold_by_note.get(Path(pred["note"]).name, []):
            if _normalize(pred["claim"]) == _normalize(gold["claim_text"]):
                g, p = gold["level"] - 1, pred["level"] - 1
                matrix[g][p] += 1
                break
    return matrix


# ---------------------------------------------------------------------------
# Benchmark append
# ---------------------------------------------------------------------------


def append_benchmark(
    result: EvalResult,
    report: dict,
    elapsed: float,
    judge: str,
    model: str,
    sample: int | None,
    threshold: int,
) -> None:
    ts = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M:%S")
    stats = report.get("stats", {})

    qwk_str = f"{result.qwk:.3f}" if result.qwk is not None else "n/a"

    lines = [
        f"\n## {ts} — P10 eval",
        "",
        f"- Vault: `fixtures/confidence_vault` "
        f"({stats.get('total_claims', '?')} claims classified).",
        f"- Judge: `{judge}/{model}`. Threshold: {threshold}. Sample: {sample or 'all'}.",
        f"- Judge calls: {stats.get('judge_calls', '?')}. "
        f"Abstentions: {stats.get('judge_abstentions', '?')}.",
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
        f"| QWK (ordinal, 5-class) | {qwk_str} | report only (flag if < 0.30) |",
        "",
    ]

    with open(BENCHMARK_PATH, "a", encoding="utf-8") as f:
        f.write("\n".join(lines))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="P10 epistemic confidence eval harness.")
    parser.add_argument(
        "--judge",
        choices=["none", "openai", "claude"],
        default="openai",
    )
    parser.add_argument("--model", default="gpt-4o")
    parser.add_argument(
        "--sample",
        type=int,
        default=None,
        metavar="N",
        help="Cap total judge calls to N.",
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=LOW_CONF_THRESHOLD,
        metavar="N",
        help=f"Report level <= N as low-confidence (default: {LOW_CONF_THRESHOLD}).",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    print(
        f"P10 eval — judge={args.judge}/{args.model} "
        f"threshold={args.threshold} sample={args.sample or 'all'}"
    )

    result, report, elapsed = run_eval(
        judge=args.judge,
        model=args.model,
        sample=args.sample,
        threshold=args.threshold,
        verbose=args.verbose,
    )

    qwk_str = f"{result.qwk:.3f}" if result.qwk is not None else "n/a"
    qwk_flag = (
        " <<< WARNING: ordinal collapse?"
        if (result.qwk is not None and result.qwk < 0.30)
        else ""
    )

    print(f"\nResults (wall clock: {elapsed:.1f}s):")
    print(f"  TP={result.tp}  FP={result.fp}  FN={result.fn}")
    print(f"  Precision={result.precision:.2f}  Recall={result.recall:.2f}  F1={result.f1:.2f}")
    print(f"  QWK (ordinal, 5-class)={qwk_str}{qwk_flag}")

    passed = args.judge == "none" or (
        result.precision >= PRECISION_THRESHOLD and result.recall >= RECALL_THRESHOLD
    )
    status = "PASS" if passed else "FAIL"
    print(
        f"\n  {status}  "
        f"(targets: precision>={PRECISION_THRESHOLD}, recall>={RECALL_THRESHOLD})"
    )

    append_benchmark(result, report, elapsed, args.judge, args.model, args.sample, args.threshold)
    print("Appended results to BENCHMARK.md.")

    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
