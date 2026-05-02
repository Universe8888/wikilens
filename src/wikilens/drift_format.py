"""Output formatters for `wikilens drift` (P8).

Mirrors contradict_format.py: pipeline stays pure, presentation lives here.
The JSON schema is part of the public interface — bump JSON_SCHEMA_VERSION
on any breaking change.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

from wikilens.drift import DriftEvent, DriftReport

JSON_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class DriftFinding:
    """A DriftEvent packaged for output (thin wrapper for report assembly)."""

    event: DriftEvent


def _ts_to_iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m-%d")


def _snippet(text: str, limit: int = 200) -> str:
    s = text.strip().replace("\n", " ")
    return s[:limit] + "..." if len(s) > limit else s


def format_markdown(report: DriftReport) -> str:
    """Human-readable grouped output, one section per note."""
    lines: list[str] = []
    lines.append(f"# Temporal drift findings — {report.vault}")
    lines.append("")

    if not report.findings:
        lines.append(
            f"No drift detected. "
            f"Walked {report.walked_commits} commits, "
            f"considered {report.pairs_considered} pairs, "
            f"filtered {report.pairs_filtered}, "
            f"judged {report.pairs_judged}."
        )
        return "\n".join(lines).rstrip() + "\n"

    lines.append(
        f"{len(report.findings)} drift event(s) across "
        f"{len({e.note_rel for e in report.findings})} note(s). "
        f"Walked {report.walked_commits} commits, "
        f"judged {report.pairs_judged} pairs."
    )
    lines.append("")

    # Group by note for readable output.
    by_note: dict[str, list[DriftEvent]] = {}
    for ev in report.findings:
        by_note.setdefault(ev.note_rel, []).append(ev)

    for note_rel, events in sorted(by_note.items()):
        lines.append(f"## {note_rel}")
        lines.append("")
        for ev in events:
            before_date = _ts_to_iso(ev.before.timestamp)
            after_date = _ts_to_iso(ev.after.timestamp)
            lines.append(
                f"### {before_date} → {after_date} "
                f"({ev.drift_type}, score {ev.score})"
            )
            lines.append("")
            lines.append(
                f"- `{ev.before.sha[:8]}` ({before_date}): "
                f"{_snippet(ev.before_claim)}"
            )
            lines.append(
                f"- `{ev.after.sha[:8]}` ({after_date}): "
                f"{_snippet(ev.after_claim)}"
            )
            lines.append("")
            lines.append(f"  _Judge:_ {ev.reasoning}")
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def format_json(report: DriftReport) -> str:
    """Stable JSON output. Sorted keys for clean diffs."""
    findings_out: list[dict] = []
    for ev in report.findings:
        findings_out.append(
            {
                "note": ev.note_rel,
                "before": {
                    "sha": ev.before.sha,
                    "date": _ts_to_iso(ev.before.timestamp),
                    "timestamp": ev.before.timestamp,
                    "claim": ev.before_claim,
                },
                "after": {
                    "sha": ev.after.sha,
                    "date": _ts_to_iso(ev.after.timestamp),
                    "timestamp": ev.after.timestamp,
                    "claim": ev.after_claim,
                },
                "type": ev.drift_type,
                "score": ev.score,
                "reasoning": ev.reasoning,
            }
        )

    doc: dict = {
        "schema_version": JSON_SCHEMA_VERSION,
        "vault": report.vault,
        "repo_root": report.repo_root,
        "stats": {
            "walked_commits": report.walked_commits,
            "pairs_considered": report.pairs_considered,
            "pairs_filtered": report.pairs_filtered,
            "pairs_judged": report.pairs_judged,
            "findings": len(report.findings),
        },
        "findings": findings_out,
    }
    return json.dumps(doc, indent=2, sort_keys=True) + "\n"
