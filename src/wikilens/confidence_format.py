"""Output formatters for `wikilens confidence` (P10).

Mirrors drift_format.py: pipeline stays pure, presentation lives here.
The JSON schema is part of the public interface — bump JSON_SCHEMA_VERSION
on any breaking change.
"""

from __future__ import annotations

import json

from wikilens.confidence import ConfidenceReport

JSON_SCHEMA_VERSION = 1

_LEVEL_LABELS = {
    1: "speculation",
    2: "conjecture",
    3: "inference",
    4: "attributed",
    5: "verified",
}


def _snippet(text: str, limit: int = 200) -> str:
    s = text.strip().replace("\n", " ")
    return s[:limit] + "..." if len(s) > limit else s


def format_markdown(report: ConfidenceReport) -> str:
    """Human-readable grouped output, one section per note."""
    lines: list[str] = []
    lines.append(f"# Epistemic confidence findings — {report.vault_path}")
    lines.append("")

    low_count = len(report.findings)
    total = report.total_claims

    if not report.findings:
        lines.append(
            f"No low-confidence claims detected (threshold ≤ {report.threshold}). "
            f"Classified {total} claim(s) across the vault."
        )
        if report.judge_abstentions:
            lines.append(f"Judge abstentions: {report.judge_abstentions}")
        return "\n".join(lines).rstrip() + "\n"

    lines.append(
        f"{low_count} low-confidence claim(s) (level ≤ {report.threshold}) "
        f"out of {total} total claims classified."
    )
    if report.judge_abstentions:
        lines.append(f"Judge abstentions: {report.judge_abstentions}")
    lines.append("")

    # Group by note
    by_note: dict[str, list] = {}
    for f in report.findings:
        by_note.setdefault(f.note_rel, []).append(f)

    for note_rel, findings in sorted(by_note.items()):
        lines.append(f"## {note_rel}")
        lines.append("")
        for f in findings:
            label = _LEVEL_LABELS.get(f.level, str(f.level))
            lines.append(
                f"- **[L{f.level} {label}]** {_snippet(f.claim_text)}"
            )
            lines.append(f"  _{f.rationale}_")
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def format_json(report: ConfidenceReport) -> str:
    """Stable JSON output. Sorted keys for clean diffs."""
    findings_out = [
        {
            "note": f.note_rel,
            "claim": f.claim_text,
            "level": f.level,
            "level_label": _LEVEL_LABELS.get(f.level, str(f.level)),
            "rationale": f.rationale,
            "judge_confidence": f.confidence,
        }
        for f in report.findings
    ]

    doc: dict = {
        "schema_version": JSON_SCHEMA_VERSION,
        "vault": report.vault_path,
        "threshold": report.threshold,
        "stats": {
            "total_claims": report.total_claims,
            "judge_calls": report.judge_calls,
            "judge_abstentions": report.judge_abstentions,
            "low_confidence_findings": len(report.findings),
        },
        "findings": findings_out,
    }
    return json.dumps(doc, indent=2, sort_keys=True) + "\n"
