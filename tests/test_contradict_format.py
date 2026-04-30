"""Tests for contradict_format.py — markdown + JSON output (P4, Phase 4.1)."""

from __future__ import annotations

import json

from wikilens.contradict import CandidatePair, ChunkRef
from wikilens.contradict_format import (
    JSON_SCHEMA_VERSION,
    ContradictReport,
    Finding,
    format_json,
    format_markdown,
)
from wikilens.judge import JudgeVerdict


def _make_report(findings: tuple[Finding, ...] = ()) -> ContradictReport:
    return ContradictReport(
        vault_root="fixtures/contradictions_vault",
        chunks_scanned=32,
        candidates=85,
        judged=40,
        judge_name="mock",
        findings=findings,
    )


def _make_finding(
    scope: str = "factual",
    score: float = 0.9,
    reasoning: str = "Paris vs Berlin — different capitals",
) -> Finding:
    pair = CandidatePair(
        a=ChunkRef(
            chunk_id="abc123",
            source_rel="capitals/paris.md",
            heading_path=("Capitals",),
            text="Paris is the capital of France.",
        ),
        b=ChunkRef(
            chunk_id="def456",
            source_rel="capitals/berlin.md",
            heading_path=("Capitals",),
            text="Berlin is the capital of France.",
        ),
        retrieval_score=0.87,
    )
    v = JudgeVerdict(verdict=True, type=scope, score=score, reasoning=reasoning)  # type: ignore[arg-type]
    return Finding(pair=pair, verdict=v)


def test_markdown_empty_report_has_header_and_zero_sections():
    md = format_markdown(_make_report())
    assert "Contradiction report" in md
    assert "0 findings" in md
    assert "## factual (0)" in md
    assert "## temporal (0)" in md
    assert "_none found._" in md


def test_markdown_groups_findings_by_type():
    f1 = _make_finding(scope="factual")
    f2 = _make_finding(scope="temporal", reasoning="older vs newer db")
    md = format_markdown(_make_report(findings=(f1, f2)))
    assert "## factual (1)" in md
    assert "## temporal (1)" in md
    # Score is rendered to 2 decimals.
    assert "(score 0.90)" in md


def test_markdown_only_filter_hides_scopes():
    f1 = _make_finding(scope="factual")
    f2 = _make_finding(scope="temporal")
    md = format_markdown(_make_report(findings=(f1, f2)), only=("factual",))
    assert "## factual (1)" in md
    assert "## temporal" not in md


def test_json_schema_fields_present():
    md = format_json(_make_report())
    doc = json.loads(md)
    assert doc["schema_version"] == JSON_SCHEMA_VERSION
    assert doc["vault_root"] == "fixtures/contradictions_vault"
    assert doc["judge"] == "mock"
    assert doc["stats"] == {
        "chunks": 32,
        "candidates": 85,
        "judged": 40,
        "findings": 0,
    }
    assert doc["findings"] == []


def test_json_finding_carries_both_chunks_and_verdict():
    f = _make_finding()
    doc = json.loads(format_json(_make_report(findings=(f,))))
    assert len(doc["findings"]) == 1
    item = doc["findings"][0]
    assert item["type"] == "factual"
    assert item["score"] == 0.9
    assert item["chunk_a"]["source_rel"] == "capitals/paris.md"
    assert item["chunk_b"]["source_rel"] == "capitals/berlin.md"
    assert item["retrieval_score"] == 0.87


def test_json_only_filter_drops_other_scopes():
    f1 = _make_finding(scope="factual")
    f2 = _make_finding(scope="temporal")
    doc = json.loads(format_json(_make_report(findings=(f1, f2)), only=("temporal",)))
    assert [f["type"] for f in doc["findings"]] == ["temporal"]
    assert doc["stats"]["findings"] == 1
