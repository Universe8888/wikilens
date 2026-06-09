"""Output formatters for `wikilens contradict`.

Mirrors the audit_format.py split: detectors/judge stay pure, presentation
lives here. The JSON schema is part of the public interface — pipelines
read it — so changes are breaking and must bump ``JSON_SCHEMA_VERSION``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from wikilens.contradict import CandidatePair
from wikilens.judge import JudgeVerdict

if TYPE_CHECKING:
    from wikilens.judge import Judge

ScopeClass = Literal["factual", "temporal"]
ALL_SCOPES: tuple[ScopeClass, ...] = ("factual", "temporal")

# Bump when the JSON output shape changes.
JSON_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Finding:
    """A judged pair that cleared the ``--min-score`` gate.

    Bundles the ``CandidatePair`` with its ``JudgeVerdict`` so both the
    markdown and JSON formatter consume a single list.
    """

    pair: CandidatePair
    verdict: JudgeVerdict


def judge_pairs(
    pairs: list[CandidatePair],
    judge: Judge,
    *,
    min_score: float,
    workers: int = 1,
) -> list[Finding]:
    """Judge every candidate pair and return findings in INPUT order (M6).

    Runs ``judge.score_pair`` over ``pairs`` with up to ``workers`` concurrent
    calls (``workers=1`` is the serial path), then keeps the pairs whose
    verdict cleared ``min_score``. Because ``parallel_map`` preserves input
    position, the findings list is identical — same members, same order — for
    any worker count, so the JSON/markdown output is stable regardless of
    concurrency. The judge must be safe to call from multiple threads; the
    networked judges are (their shared cost gate and cache are locked).
    """
    from wikilens.executor import parallel_map

    verdicts = parallel_map(
        lambda p: judge.score_pair(p.a.text, p.b.text),
        pairs,
        max_workers=workers,
    )
    return [
        Finding(pair=p, verdict=v)
        for p, v in zip(pairs, verdicts, strict=True)
        if v.verdict and v.score >= min_score
    ]


@dataclass(frozen=True)
class ContradictReport:
    """Container for one `wikilens contradict` run."""

    vault_root: str
    chunks_scanned: int
    candidates: int
    judged: int
    judge_name: str
    findings: tuple[Finding, ...]

    @property
    def total_findings(self) -> int:
        return len(self.findings)


def _filter_scopes(only: tuple[ScopeClass, ...] | None) -> set[str]:
    return set(only) if only else set(ALL_SCOPES)


def _snippet(text: str, limit: int = 240) -> str:
    s = text.strip().replace("\n", " ")
    if len(s) > limit:
        s = s[:limit] + "..."
    return s


def format_markdown(
    report: ContradictReport,
    only: tuple[ScopeClass, ...] | None = None,
) -> str:
    """Human-readable grouped output, one section per contradiction class."""
    mask = _filter_scopes(only)
    lines: list[str] = []
    lines.append(f"# Contradiction report — {report.vault_root}")
    lines.append("")
    lines.append(
        f"Scanned {report.chunks_scanned} chunks, "
        f"{report.candidates} candidate pairs, "
        f"{report.judged} judged, "
        f"{report.total_findings} findings. "
        f"(judge: {report.judge_name})"
    )
    lines.append("")

    # Group findings by verdict type for stable section ordering.
    for scope in ALL_SCOPES:
        if scope not in mask:
            continue
        group = [f for f in report.findings if f.verdict.type == scope]
        lines.append(f"## {scope} ({len(group)})")
        if not group:
            lines.append("_none found._")
        else:
            for f in group:
                a_head = " > ".join(f.pair.a.heading_path) or "(no heading)"
                b_head = " > ".join(f.pair.b.heading_path) or "(no heading)"
                lines.append(
                    f"### `{f.pair.a.source_rel}` vs `{f.pair.b.source_rel}` "
                    f"(score {f.verdict.score:.2f})"
                )
                lines.append(f"- **A:** `{f.pair.a.source_rel}` — {a_head}")
                lines.append(f"  > {_snippet(f.pair.a.text)}")
                lines.append(f"- **B:** `{f.pair.b.source_rel}` — {b_head}")
                lines.append(f"  > {_snippet(f.pair.b.text)}")
                lines.append(f"- **Judge:** {f.verdict.reasoning}")
                lines.append("")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def format_json(
    report: ContradictReport,
    only: tuple[ScopeClass, ...] | None = None,
) -> str:
    """Stable JSON. Sorted keys so diffs are clean."""
    mask = _filter_scopes(only)
    findings_out: list[dict] = []
    for f in report.findings:
        if f.verdict.type not in mask:
            continue
        findings_out.append(
            {
                "type": f.verdict.type,
                "score": f.verdict.score,
                "reasoning": f.verdict.reasoning,
                "chunk_a": {
                    "id": f.pair.a.chunk_id,
                    "source_rel": f.pair.a.source_rel,
                    "heading_path": list(f.pair.a.heading_path),
                    "text": f.pair.a.text,
                },
                "chunk_b": {
                    "id": f.pair.b.chunk_id,
                    "source_rel": f.pair.b.source_rel,
                    "heading_path": list(f.pair.b.heading_path),
                    "text": f.pair.b.text,
                },
                "retrieval_score": f.pair.retrieval_score,
            }
        )

    doc: dict = {
        "schema_version": JSON_SCHEMA_VERSION,
        "vault_root": report.vault_root,
        "judge": report.judge_name,
        "stats": {
            "chunks": report.chunks_scanned,
            "candidates": report.candidates,
            "judged": report.judged,
            "findings": len(findings_out),
        },
        "findings": findings_out,
    }
    return json.dumps(doc, indent=2, sort_keys=True) + "\n"
