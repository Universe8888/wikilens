"""P3 eval harness — precision/recall/F1 per defect class vs. hand-labeled
ground truth, appended to BENCHMARK.md in the same additive style as eval_p2.py.

Usage:
    python scripts/eval_p3.py \\
        --vault fixtures/audit_vault \\
        --truth fixtures/eval/p3_ground_truth.json

No model loading, no LanceDB — just walks the fixture, runs the detectors,
compares set-wise against ground truth. Seconds to run.

Outputs:
    - Human-readable P/R/F1 table to stdout.
    - Appends a timestamped section to BENCHMARK.md (top of file).

Exit code: always 0. Reporting tool, not a gate.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from wikilens.audit import audit_vault

REPO_ROOT = Path(__file__).resolve().parent.parent


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


def _load_truth(path: Path) -> dict[str, list[dict]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        "broken": data.get("broken", []),
        "one_way": data.get("one_way", []),
        "orphans": data.get("orphans", []),
        "shadowed": data.get("shadowed", []),
    }


def _score(name: str, actual: set, expected: set) -> ClassReport:
    tp = len(actual & expected)
    fp = len(actual - expected)
    fn = len(expected - actual)
    return ClassReport(name=name, tp=tp, fp=fp, fn=fn)


def _to_key_broken(d: dict) -> tuple:
    return (d["source"], d["target_raw"])


def _to_key_one_way(d: dict) -> tuple:
    return (d["source"], d["target"])


def _to_key_orphan(d: dict) -> tuple:
    return (d["node"],)


def _to_key_shadowed(d: dict) -> tuple:
    return (d["source"], d["target_raw"], tuple(sorted(d["candidates"])))


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
    node_count: int,
    total_findings: int,
    path: Path,
) -> None:
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    section = (
        f"\n## {timestamp} — P3 eval ({_git_rev()})\n\n"
        f"- Vault: `{vault.as_posix()}` ({node_count} notes).\n"
        f"- Findings: {total_findings} across four defect classes.\n"
        f"- Detectors: pure functions over the in-memory link graph, no models.\n\n"
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
        "  ```\n\n"
        "Each harness **appends** a timestamped section below; prior runs are "
        "preserved so regressions are visible side-by-side.\n"
    )
    if path.exists():
        prior = path.read_text(encoding="utf-8")
        if prior.startswith("# Benchmark"):
            # Split off the existing header (everything before the first dated
            # section) and replace it with the canonical one, then prepend our
            # new section above the prior dated sections.
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
    p.add_argument("--vault", type=Path, default=Path("fixtures/audit_vault"))
    p.add_argument(
        "--truth", type=Path, default=Path("fixtures/eval/p3_ground_truth.json")
    )
    p.add_argument("--benchmark", type=Path, default=Path("BENCHMARK.md"))
    args = p.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

    print(f"[audit] {args.vault}")
    report = audit_vault(args.vault)
    print(
        f"  nodes={report.node_count}  "
        f"broken={len(report.broken)}  one_way={len(report.one_way)}  "
        f"orphans={len(report.orphans)}  shadowed={len(report.shadowed)}"
    )

    truth = _load_truth(args.truth)

    actual_broken = {(b.source, b.target_raw) for b in report.broken}
    expected_broken = {_to_key_broken(d) for d in truth["broken"]}

    actual_one_way = {(o.source, o.target) for o in report.one_way}
    expected_one_way = {_to_key_one_way(d) for d in truth["one_way"]}

    actual_orphans = {(o.node,) for o in report.orphans}
    expected_orphans = {_to_key_orphan(d) for d in truth["orphans"]}

    actual_shadowed = {
        (s.source, s.target_raw, tuple(sorted(s.candidates)))
        for s in report.shadowed
    }
    expected_shadowed = {_to_key_shadowed(d) for d in truth["shadowed"]}

    reports = [
        _score("broken",   actual_broken,   expected_broken),
        _score("one_way",  actual_one_way,  expected_one_way),
        _score("orphans",  actual_orphans,  expected_orphans),
        _score("shadowed", actual_shadowed, expected_shadowed),
    ]

    table = format_table(reports)
    print()
    print(table)

    # Show what diverged, if anything, to make failures self-diagnosing.
    divergence_blocks: list[str] = []
    for name, actual, expected in [
        ("broken",   actual_broken,   expected_broken),
        ("one_way",  actual_one_way,  expected_one_way),
        ("orphans",  actual_orphans,  expected_orphans),
        ("shadowed", actual_shadowed, expected_shadowed),
    ]:
        extra = actual - expected
        missing = expected - actual
        if extra or missing:
            block = [f"\n{name}:"]
            for e in sorted(extra):
                block.append(f"  + unexpected: {e}")
            for m in sorted(missing):
                block.append(f"  - missing:    {m}")
            divergence_blocks.append("\n".join(block))
    if divergence_blocks:
        print("\n[divergence]" + "".join(divergence_blocks))
    else:
        print("\n[ok] detector output matches ground truth exactly.")

    write_benchmark_md(
        reports=reports,
        table=table,
        vault=args.vault,
        node_count=report.node_count,
        total_findings=report.total_findings,
        path=args.benchmark,
    )
    print(f"\nwrote {args.benchmark}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
