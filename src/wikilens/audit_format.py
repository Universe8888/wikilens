"""Output formatters for `wikilens audit`.

Separated from `audit.py` so the detectors stay pure-function / test-only
and the CLI-facing presentation logic lives in its own module. The JSON
schema here is part of the public interface — pipelines read it — so
schema changes are breaking and should bump a version field.
"""

from __future__ import annotations

import json
from typing import Literal

from wikilens.audit import AuditReport

DefectClass = Literal["broken", "one-way", "orphan", "shadowed"]
ALL_CLASSES: tuple[DefectClass, ...] = ("broken", "one-way", "orphan", "shadowed")

# Bump when the JSON output shape changes.
JSON_SCHEMA_VERSION = 1


def _filter_mask(only: tuple[DefectClass, ...] | None) -> set[DefectClass]:
    return set(only) if only else set(ALL_CLASSES)


def format_markdown(
    report: AuditReport,
    only: tuple[DefectClass, ...] | None = None,
) -> str:
    """Human-readable grouped output. Empty classes still print a line
    so the user can confirm the check ran."""
    mask = _filter_mask(only)
    lines: list[str] = []
    lines.append(f"# Link audit — {report.vault_root.name}")
    lines.append("")
    lines.append(f"Scanned {report.node_count} notes. {report.total_findings} findings.")
    lines.append("")

    if "broken" in mask:
        lines.append(f"## Broken links ({len(report.broken)})")
        if not report.broken:
            lines.append("_none found._")
        else:
            for b in report.broken:
                arrow = "![[...]]" if b.is_embed else "[[...]]"
                lines.append(f"- `{b.source}` → `{b.target_raw}` {arrow}")
        lines.append("")

    if "one-way" in mask:
        lines.append(f"## One-way links ({len(report.one_way)})")
        if not report.one_way:
            lines.append("_none found._")
        else:
            for o in report.one_way:
                lines.append(f"- `{o.source}` → `{o.target}` (no backlink)")
        lines.append("")

    if "orphan" in mask:
        lines.append(f"## Orphan notes ({len(report.orphans)})")
        if not report.orphans:
            lines.append("_none found._")
        else:
            for o in report.orphans:
                lines.append(f"- `{o.node}` ({o.outbound_count} outbound, 0 inbound)")
        lines.append("")

    if "shadowed" in mask:
        lines.append(f"## Shadowed links ({len(report.shadowed)})")
        if not report.shadowed:
            lines.append("_none found._")
        else:
            for s in report.shadowed:
                cands = ", ".join(f"`{c}`" for c in s.candidates)
                lines.append(f"- `{s.source}` → `{s.target_raw}` (candidates: {cands})")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def format_json(
    report: AuditReport,
    only: tuple[DefectClass, ...] | None = None,
) -> str:
    """Stable JSON. Sorted keys so diffs are clean."""
    mask = _filter_mask(only)
    doc: dict = {
        "schema_version": JSON_SCHEMA_VERSION,
        "vault_root": str(report.vault_root),
        "node_count": report.node_count,
        "total_findings": report.total_findings,
    }

    if "broken" in mask:
        doc["broken"] = [
            {"source": b.source, "target_raw": b.target_raw, "is_embed": b.is_embed}
            for b in report.broken
        ]
    if "one-way" in mask:
        doc["one_way"] = [
            {"source": o.source, "target": o.target, "target_raw": o.target_raw}
            for o in report.one_way
        ]
    if "orphan" in mask:
        doc["orphans"] = [
            {"node": o.node, "outbound_count": o.outbound_count}
            for o in report.orphans
        ]
    if "shadowed" in mask:
        doc["shadowed"] = [
            {
                "source": s.source,
                "target_raw": s.target_raw,
                "candidates": list(s.candidates),
            }
            for s in report.shadowed
        ]

    return json.dumps(doc, indent=2, sort_keys=True) + "\n"
