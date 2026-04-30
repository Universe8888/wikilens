"""Snapshot-ish tests for gap_format.py (P5, Phase 5.1)."""

from __future__ import annotations

import json

import numpy as np

from wikilens.gap import ChunkPoint, Cluster
from wikilens.gap_format import GapReport, format_json, format_markdown
from wikilens.generator import GapCandidate, GapFinding


def _point(chunk_id: str) -> ChunkPoint:
    return ChunkPoint(
        chunk_id=chunk_id,
        source_rel=f"{chunk_id}.md",
        text="body",
        vector=np.asarray([0.0, 0.0], dtype=np.float32),
    )


def _sample_report(with_findings: bool = True) -> GapReport:
    cluster = Cluster(cluster_id=3, points=(_point("c1"), _point("c2"), _point("c3")))
    findings: tuple[GapFinding, ...] = ()
    if with_findings:
        findings = (
            GapFinding(
                cluster_id=3,
                cluster_size=3,
                candidate=GapCandidate(
                    gap_question="What is the Calvin cycle?",
                    suggested_note_title="calvin-cycle",
                    rationale="notes describe light reactions but not dark reactions",
                    supporting_chunk_ids=("c1", "c2"),
                ),
            ),
        )
    return GapReport(
        vault_root="fixtures/gaps_vault",
        chunks_scanned=3,
        clusters=(cluster,),
        clusters_processed=1,
        findings=findings,
        generator_name="mock",
    )


def test_format_markdown_includes_vault_and_stats():
    out = format_markdown(_sample_report())
    assert "fixtures/gaps_vault" in out
    assert "3 chunks" in out
    assert "1 clusters" in out
    assert "mock" in out


def test_format_markdown_renders_each_finding():
    out = format_markdown(_sample_report())
    assert "### What is the Calvin cycle?" in out
    assert "`calvin-cycle`" in out
    assert "`c1`" in out
    assert "## Cluster 3" in out


def test_format_markdown_no_findings_is_graceful():
    out = format_markdown(_sample_report(with_findings=False))
    assert "no gaps found" in out.lower()
    assert "Cluster 3" not in out


def test_format_json_is_valid_and_versioned():
    out = format_json(_sample_report())
    doc = json.loads(out)
    assert doc["schema_version"] == 1
    assert doc["vault_root"] == "fixtures/gaps_vault"
    assert doc["generator"] == "mock"
    assert doc["stats"]["chunks"] == 3
    assert doc["stats"]["findings"] == 1
    assert len(doc["clusters"]) == 1
    assert doc["clusters"][0]["chunk_ids"] == ["c1", "c2", "c3"]
    assert len(doc["findings"]) == 1
    assert doc["findings"][0]["suggested_note_title"] == "calvin-cycle"


def test_format_json_sorts_keys_for_stable_diffs():
    out = format_json(_sample_report())
    # sort_keys=True means schema_version appears after 'findings'/'clusters'
    # alphabetically. We're just asserting the output round-trips cleanly.
    doc = json.loads(out)
    reserialized = json.dumps(doc, indent=2, sort_keys=True) + "\n"
    assert out == reserialized
