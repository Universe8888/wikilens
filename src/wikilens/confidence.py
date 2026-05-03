"""Epistemic Confidence Mapper — claim extractor + classifier pipeline (P10).

Pipeline:
  1. enumerate_notes()     — walk vault directory, return .md paths.
  2. extract_claims()      — reuse drift.extract_claims(); strip structural markdown.
  3. pack_context()        — build ±2-sentence window around each claim.
  4. run_confidence()      — iterate judge over claims; apply threshold + sample filters.

The confidence judge lives in confidence_judge.py; formatting in confidence_format.py.
This module owns no LLM and no network calls.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from wikilens.drift import extract_claims

if TYPE_CHECKING:
    from wikilens.confidence_judge import ConfidenceJudge


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ClaimRecord:
    """One sentence extracted from a note, with its context window."""

    note_rel: str       # path relative to vault root
    claim_text: str
    context: str        # ±2-sentence window (includes the claim itself)
    sentence_index: int # 0-based index within the note's sentence list


@dataclass(frozen=True)
class ConfidenceVerdict:
    """Judge output for a single claim."""

    level: int          # 1–5
    rationale: str      # judge's one-sentence explanation
    confidence: float   # 0.0–1.0, judge's self-reported certainty


@dataclass(frozen=True)
class ConfidenceFinding:
    """A claim whose verdict level is at or below the reporting threshold."""

    note_rel: str
    claim_text: str
    level: int
    rationale: str
    confidence: float


@dataclass
class ConfidenceReport:
    """Full output from one confidence run over a vault."""

    vault_path: str
    threshold: int
    total_claims: int
    judge_calls: int
    judge_abstentions: int
    findings: list[ConfidenceFinding] = field(default_factory=list)

    @property
    def has_findings(self) -> bool:
        return bool(self.findings)


# ---------------------------------------------------------------------------
# Note enumeration
# ---------------------------------------------------------------------------


def enumerate_notes(vault_path: str, only: str | None = None) -> list[Path]:
    """Return sorted list of .md paths under vault_path.

    Args:
        vault_path: directory to walk.
        only: if provided, restrict to notes whose basename matches this string
              (case-insensitive). Useful for --only flag.
    """
    root = Path(vault_path)
    notes = sorted(root.rglob("*.md"))
    if only:
        only_lower = only.lower()
        notes = [p for p in notes if only_lower in p.name.lower()]
    return notes


# ---------------------------------------------------------------------------
# Context packing
# ---------------------------------------------------------------------------

_CONTEXT_WINDOW = 2  # sentences on each side of the claim


def pack_context(sentences: list[str], idx: int) -> str:
    """Return the claim sentence plus ±_CONTEXT_WINDOW surrounding sentences."""
    lo = max(0, idx - _CONTEXT_WINDOW)
    hi = min(len(sentences), idx + _CONTEXT_WINDOW + 1)
    return " ".join(sentences[lo:hi])


# ---------------------------------------------------------------------------
# Main pipeline entry point
# ---------------------------------------------------------------------------


def run_confidence(
    vault_path: str,
    judge: ConfidenceJudge,
    threshold: int = 2,
    sample: int | None = None,
    only: str | None = None,
    min_confidence: float = 0.0,
) -> ConfidenceReport:
    """Run the epistemic confidence pipeline over a vault.

    Args:
        vault_path:     path to the vault directory.
        judge:          ConfidenceJudge instance (Mock / OpenAI / Claude).
        threshold:      report claims whose level <= this value (default 2).
        sample:         if set, cap total judge calls to this number.
        only:           restrict to a single note (basename substring match).
        min_confidence: drop verdicts whose judge confidence < this value.

    Returns:
        ConfidenceReport with findings sorted by (note_rel, sentence_index).
    """
    notes = enumerate_notes(vault_path, only=only)

    # Build full claim list
    all_records: list[ClaimRecord] = []
    for note_path in notes:
        try:
            text = note_path.read_text(encoding="utf-8")
        except OSError:
            continue
        sentences = extract_claims(text)
        if not sentences:
            continue
        rel = str(note_path.relative_to(vault_path)).replace(os.sep, "/")
        for idx, sent in enumerate(sentences):
            context = pack_context(sentences, idx)
            all_records.append(ClaimRecord(
                note_rel=rel,
                claim_text=sent,
                context=context,
                sentence_index=idx,
            ))

    # Apply sample cap
    records_to_judge = all_records
    if sample is not None:
        records_to_judge = all_records[:sample]

    findings: list[ConfidenceFinding] = []
    judge_calls = 0
    judge_abstentions = 0

    for record in records_to_judge:
        verdict = judge.classify(record.claim_text, record.context)
        judge_calls += 1
        if verdict.confidence == 0.0 and verdict.level == 3:
            # Sentinel returned on exhausted retries
            judge_abstentions += 1

        if verdict.confidence < min_confidence:
            continue
        if verdict.level <= threshold:
            findings.append(ConfidenceFinding(
                note_rel=record.note_rel,
                claim_text=record.claim_text,
                level=verdict.level,
                rationale=verdict.rationale,
                confidence=verdict.confidence,
            ))

    findings.sort(key=lambda f: (f.note_rel, f.level))

    return ConfidenceReport(
        vault_path=vault_path,
        threshold=threshold,
        total_claims=len(all_records),
        judge_calls=judge_calls,
        judge_abstentions=judge_abstentions,
        findings=findings,
    )
