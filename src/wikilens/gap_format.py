"""Output formatters for `wikilens gap`.

Mirrors the audit_format.py / contradict_format.py split: the gap
pipeline + generator stay pure-logic, presentation lives here. The
JSON schema is part of the public interface — pipelines read it — so
changes are breaking and must bump ``JSON_SCHEMA_VERSION``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from wikilens.gap import Cluster
from wikilens.generator import GapFinding

# Bump when the JSON output shape changes.
JSON_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class GapReport:
    """Container for one `wikilens gap` run."""

    vault_root: str
    chunks_scanned: int
    clusters: tuple[Cluster, ...]
    clusters_processed: int
    findings: tuple[GapFinding, ...]
    generator_name: str

    @property
    def total_findings(self) -> int:
        return len(self.findings)

    @property
    def total_clusters(self) -> int:
        return len(self.clusters)


def _snippet(text: str, limit: int = 180) -> str:
    s = text.strip().replace("\n", " ")
    if len(s) > limit:
        s = s[:limit] + "..."
    return s


def format_markdown(report: GapReport) -> str:
    """Human-readable grouped output, one section per cluster that produced findings."""
    lines: list[str] = []
    lines.append(f"# Gap report — {report.vault_root}")
    lines.append("")
    lines.append(
        f"Scanned {report.chunks_scanned} chunks, "
        f"{report.total_clusters} clusters (processed {report.clusters_processed}), "
        f"{report.total_findings} gap candidates. "
        f"(generator: {report.generator_name})"
    )
    lines.append("")

    if not report.findings:
        lines.append("_no gaps found._")
        return "\n".join(lines).rstrip() + "\n"

    # Group findings by cluster_id for stable output. Order mirrors the
    # cluster list (largest first, tie-break by cluster_id).
    cluster_order = [c.cluster_id for c in report.clusters]
    by_cluster: dict[int, list[GapFinding]] = {}
    for f in report.findings:
        by_cluster.setdefault(f.cluster_id, []).append(f)

    for cluster_id in cluster_order:
        group = by_cluster.get(cluster_id, [])
        if not group:
            continue
        size = group[0].cluster_size
        lines.append(f"## Cluster {cluster_id} ({size} chunks)")
        lines.append("")
        for f in group:
            c = f.candidate
            lines.append(f"### {c.gap_question}")
            lines.append(f"- **Rationale:** {_snippet(c.rationale)}")
            if c.supporting_chunk_ids:
                ids = ", ".join(f"`{cid}`" for cid in c.supporting_chunk_ids)
                lines.append(f"- **Supporting chunks:** {ids}")
            lines.append(f"- **Suggested note:** `{c.suggested_note_title}`")
            lines.append("")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def format_json(report: GapReport) -> str:
    """Stable JSON. Sorted keys so diffs are clean."""
    findings_out = [
        {
            "cluster_id": f.cluster_id,
            "cluster_size": f.cluster_size,
            "gap_question": f.candidate.gap_question,
            "suggested_note_title": f.candidate.suggested_note_title,
            "rationale": f.candidate.rationale,
            "supporting_chunk_ids": list(f.candidate.supporting_chunk_ids),
        }
        for f in report.findings
    ]
    clusters_out = [
        {
            "cluster_id": c.cluster_id,
            "size": c.size,
            "chunk_ids": [p.chunk_id for p in c.points],
        }
        for c in report.clusters
    ]
    doc: dict = {
        "schema_version": JSON_SCHEMA_VERSION,
        "vault_root": report.vault_root,
        "generator": report.generator_name,
        "stats": {
            "chunks": report.chunks_scanned,
            "clusters": report.total_clusters,
            "clusters_processed": report.clusters_processed,
            "findings": report.total_findings,
        },
        "clusters": clusters_out,
        "findings": findings_out,
    }
    return json.dumps(doc, indent=2, sort_keys=True) + "\n"
