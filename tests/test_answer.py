"""Tests for P6 answer dataclasses and plumbing (steps 1, 3, 5, 7).

Retrieval (step 4) is tested via the pipeline (step 5) using a
mini LanceDB fixture. CLI is step 8.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from wikilens.answer import (
    AnswerDraft,
    AnswerReport,
    AttributionReport,
    Citation,
    GapInput,
    SupportingChunk,
    check_attribution,
    draft_answers,
    load_gaps,
)


def test_gap_input_round_trips_fields():
    g = GapInput(
        cluster_id=3,
        cluster_size=5,
        gap_question="What is the Calvin cycle?",
        suggested_note_title="calvin-cycle",
        rationale="three notes describe light reactions but none explain dark reactions",
        supporting_chunk_ids=("c1", "c2"),
    )
    assert g.cluster_id == 3
    assert g.suggested_note_title == "calvin-cycle"
    assert g.supporting_chunk_ids == ("c1", "c2")


def test_gap_input_supporting_chunks_defaults_empty():
    g = GapInput(
        cluster_id=0,
        cluster_size=3,
        gap_question="q?",
        suggested_note_title="q",
        rationale="r",
    )
    assert g.supporting_chunk_ids == ()


def test_supporting_chunk_preserves_retrieval_metadata():
    s = SupportingChunk(
        chunk_id="abc123",
        source_rel="photosynthesis.md",
        heading_path=("Light reactions",),
        text="ATP and NADPH are produced in the thylakoid membranes.",
        retrieval_rank=1,
        retrieval_score=0.87,
    )
    assert s.retrieval_rank == 1
    assert s.heading_path == ("Light reactions",)


def test_citation_holds_footnote_and_chunk_id():
    c = Citation(footnote_id=1, chunk_id="abc123", snippet="ATP and NADPH...")
    assert c.footnote_id == 1
    assert c.chunk_id == "abc123"


def test_attribution_report_rate_on_empty_draft():
    # External-research stubs have zero sentences; rate is vacuously 1.0
    # so they don't drag the aggregate attribution metric down.
    r = AttributionReport(total_sentences=0, cited_sentences=0)
    assert r.attribution_rate == 1.0
    assert r.is_clean


def test_attribution_report_rate_partial():
    r = AttributionReport(total_sentences=5, cited_sentences=4)
    assert r.attribution_rate == 0.8
    assert r.is_clean


def test_attribution_report_flags_orphan_footnote():
    r = AttributionReport(
        total_sentences=3,
        cited_sentences=3,
        orphan_footnotes=(2,),
    )
    assert not r.is_clean
    assert r.orphan_footnotes == (2,)


def test_attribution_report_flags_invalid_chunk_ref():
    r = AttributionReport(
        total_sentences=3,
        cited_sentences=3,
        invalid_chunk_refs=("ghost-chunk",),
    )
    assert not r.is_clean
    assert r.invalid_chunk_refs == ("ghost-chunk",)


def _mk_gap() -> GapInput:
    return GapInput(
        cluster_id=0,
        cluster_size=3,
        gap_question="q?",
        suggested_note_title="q",
        rationale="r",
    )


def _mk_draft(skipped: bool = False, strength: str = "strong") -> AnswerDraft:
    return AnswerDraft(
        gap=_mk_gap(),
        supporting_chunks=(),
        evidence_strength=strength,  # type: ignore[arg-type]
        body_markdown="",
        citations=(),
        attribution=AttributionReport(total_sentences=0, cited_sentences=0),
        drafter_name="mock",
        model="mock",
        skipped=skipped,
        skip_reason="min-supporting not met" if skipped else "",
    )


def test_answer_draft_defaults_to_non_skipped():
    d = _mk_draft()
    assert not d.skipped
    assert d.skip_reason == ""


def test_answer_draft_records_skip_reason():
    d = _mk_draft(skipped=True)
    assert d.skipped
    assert d.skip_reason == "min-supporting not met"


def test_answer_report_counts_are_consistent():
    drafts = (
        _mk_draft(strength="strong"),
        _mk_draft(strength="thin"),
        _mk_draft(strength="external-research"),
        _mk_draft(skipped=True),
    )
    report = AnswerReport(
        vault_root="fixtures/gaps_vault",
        gaps_path="gaps.json",
        drafter_name="mock",
        model="mock",
        retrieval_mode="rerank",
        top_k=8,
        min_supporting=2,
        drafts=drafts,
    )
    assert report.total_drafts == 4
    assert report.total_skipped == 1
    assert report.total_external_research == 1
    assert report.total_drafted == 3


# ─── load_gaps ────────────────────────────────────────────────────────────────


def _mk_gaps_json(findings: list[dict], schema_version: int = 1) -> str:
    return json.dumps({"schema_version": schema_version, "findings": findings})


_VALID_FINDING = {
    "cluster_id": 3,
    "cluster_size": 5,
    "gap_question": "What is the Calvin cycle?",
    "suggested_note_title": "calvin-cycle",
    "rationale": "notes describe light reactions but not dark reactions",
    "supporting_chunk_ids": ["c1", "c2"],
}


def test_load_gaps_parses_valid_file(tmp_path: Path):
    p = tmp_path / "gaps.json"
    p.write_text(_mk_gaps_json([_VALID_FINDING]))
    gaps = load_gaps(p)
    assert len(gaps) == 1
    g = gaps[0]
    assert g.cluster_id == 3
    assert g.suggested_note_title == "calvin-cycle"
    assert g.supporting_chunk_ids == ("c1", "c2")


def test_load_gaps_multiple_findings(tmp_path: Path):
    findings = [_VALID_FINDING, {**_VALID_FINDING, "suggested_note_title": "other-stub"}]
    p = tmp_path / "gaps.json"
    p.write_text(_mk_gaps_json(findings))
    gaps = load_gaps(p)
    assert len(gaps) == 2


def test_load_gaps_empty_supporting_ids(tmp_path: Path):
    finding = {**_VALID_FINDING, "supporting_chunk_ids": []}
    p = tmp_path / "gaps.json"
    p.write_text(_mk_gaps_json([finding]))
    gaps = load_gaps(p)
    assert gaps[0].supporting_chunk_ids == ()


def test_load_gaps_missing_supporting_ids_key(tmp_path: Path):
    finding = {k: v for k, v in _VALID_FINDING.items() if k != "supporting_chunk_ids"}
    p = tmp_path / "gaps.json"
    p.write_text(_mk_gaps_json([finding]))
    gaps = load_gaps(p)
    assert gaps[0].supporting_chunk_ids == ()


def test_load_gaps_wrong_schema_version(tmp_path: Path):
    p = tmp_path / "gaps.json"
    p.write_text(_mk_gaps_json([_VALID_FINDING], schema_version=99))
    with pytest.raises(ValueError, match="schema_version"):
        load_gaps(p)


def test_load_gaps_missing_findings_key(tmp_path: Path):
    p = tmp_path / "gaps.json"
    p.write_text(json.dumps({"schema_version": 1}))
    with pytest.raises(ValueError, match="findings"):
        load_gaps(p)


def test_load_gaps_finding_missing_required_key(tmp_path: Path):
    finding = {k: v for k, v in _VALID_FINDING.items() if k != "gap_question"}
    p = tmp_path / "gaps.json"
    p.write_text(_mk_gaps_json([finding]))
    with pytest.raises(ValueError, match="gap_question"):
        load_gaps(p)


def test_load_gaps_file_not_found():
    with pytest.raises(ValueError, match="not found"):
        load_gaps("/nonexistent/gaps.json")


def test_load_gaps_invalid_json(tmp_path: Path):
    p = tmp_path / "gaps.json"
    p.write_text("not json {")
    with pytest.raises(ValueError, match="not valid JSON"):
        load_gaps(p)


# ─── check_attribution ────────────────────────────────────────────────────────

_BODY_ALL_CITED = """\
## What the vault says

The vault notes that ATP and NADPH are produced.[^1]
Chlorophyll absorbs photons at 680nm.[^2]

## Evidence gaps

- RuBisCO not covered.

## Related notes

## Citations

[^1]: `chunk-a` — "ATP and NADPH are produced..."
[^2]: `chunk-b` — "Chlorophyll absorbs at 680nm..."
"""

_BODY_NO_CITATIONS = """\
## What the vault says

The vault has no relevant coverage for this question.

## Evidence gaps

- External sources required.

## Related notes

## Citations

_No citations — external research required._
"""

_BODY_ORPHAN_FOOTNOTE = """\
## What the vault says

The vault notes ATP production.[^1] Also something else.[^99]

## Evidence gaps

- missing info

## Related notes

## Citations

[^1]: `chunk-a` — "ATP production..."
"""

_BODY_INVALID_CHUNK_REF = """\
## What the vault says

The vault notes ATP production.[^1]

## Evidence gaps

- missing info

## Related notes

## Citations

[^1]: `ghost-chunk` — "ATP production..."
"""


def test_check_attribution_all_cited():
    report, citations = check_attribution(_BODY_ALL_CITED, {"chunk-a", "chunk-b"})
    assert report.total_sentences == 2
    assert report.cited_sentences == 2
    assert report.attribution_rate == 1.0
    assert report.is_clean
    assert len(citations) == 2


def test_check_attribution_external_research_stub():
    report, citations = check_attribution(_BODY_NO_CITATIONS, set())
    assert report.total_sentences == 0
    assert report.attribution_rate == 1.0
    assert report.is_clean
    assert citations == ()


def test_check_attribution_orphan_footnote():
    report, _ = check_attribution(_BODY_ORPHAN_FOOTNOTE, {"chunk-a"})
    assert 99 in report.orphan_footnotes
    assert not report.is_clean


def test_check_attribution_invalid_chunk_ref():
    report, _ = check_attribution(_BODY_INVALID_CHUNK_REF, {"real-chunk"})
    assert "ghost-chunk" in report.invalid_chunk_refs
    assert not report.is_clean


def test_check_attribution_valid_chunk_ref():
    report, _ = check_attribution(_BODY_INVALID_CHUNK_REF, {"ghost-chunk"})
    assert report.is_clean


# ─── draft_answers pipeline (MockDrafter, mock store) ────────────────────────


def _mk_gap_input(title: str = "calvin-cycle") -> GapInput:
    return GapInput(
        cluster_id=0,
        cluster_size=3,
        gap_question="What is the Calvin cycle?",
        suggested_note_title=title,
        rationale="notes describe light reactions but not dark",
        supporting_chunk_ids=("c1",),
    )


def _mk_mock_store() -> MagicMock:
    """Minimal mock that satisfies retrieve_support's needs.

    search_dense / search_fts return one hit each; the full-table scan
    (used to pull missing supporting_chunk_ids) returns an empty list
    so the pipeline relies only on the query results.
    """
    from wikilens.store import SearchHit

    hit = SearchHit(
        chunk_id="c1",
        source_rel="photosynthesis.md",
        heading_path=("Light reactions",),
        text="Light reactions produce ATP and NADPH.",
        score=0.9,
    )
    store = MagicMock()
    store.search_dense.return_value = [hit]
    store.search_fts.return_value = [hit]
    # Full-table scan returns empty (no extra gaps_hint lookup needed here).
    table_mock = MagicMock()
    table_mock.to_arrow.return_value.to_pylist.return_value = []
    store._get_or_create_table.return_value = table_mock
    return store


def _mk_mock_embedder() -> MagicMock:
    import numpy as np

    embedder = MagicMock()
    embedder.encode_query.return_value = np.zeros(384, dtype=np.float32)
    return embedder


def test_draft_answers_single_gap_produces_draft():
    from wikilens.drafter import MockDrafter

    gaps = [_mk_gap_input()]
    store = _mk_mock_store()
    embedder = _mk_mock_embedder()
    drafter = MockDrafter()

    drafts = draft_answers(
        gaps, store, embedder, drafter,
        top_k=5, mode="hybrid", min_supporting=1,
    )
    assert len(drafts) == 1
    d = drafts[0]
    assert d.gap.suggested_note_title == "calvin-cycle"
    assert not d.skipped
    assert d.body_markdown
    assert d.evidence_strength in ("strong", "thin", "external-research")


def test_draft_answers_external_research_when_below_min_supporting():
    from wikilens.drafter import MockDrafter

    gaps = [_mk_gap_input()]
    store = _mk_mock_store()
    embedder = _mk_mock_embedder()
    drafter = MockDrafter()

    # min_supporting=99 forces external-research path
    drafts = draft_answers(
        gaps, store, embedder, drafter,
        top_k=5, mode="hybrid", min_supporting=99,
    )
    assert len(drafts) == 1
    assert drafts[0].evidence_strength == "external-research"
    assert not drafts[0].skipped  # not skipped — emitted as external-research stub


def test_draft_answers_sample_caps_results():
    from wikilens.drafter import MockDrafter

    gaps = [_mk_gap_input(f"gap-{i}") for i in range(5)]
    store = _mk_mock_store()
    embedder = _mk_mock_embedder()
    drafter = MockDrafter()

    drafts = draft_answers(
        gaps, store, embedder, drafter,
        top_k=5, mode="hybrid", min_supporting=1, sample=2,
    )
    assert len(drafts) == 2


def test_draft_answers_multiple_gaps_calls_drafter_per_gap():
    from wikilens.drafter import MockDrafter

    gaps = [_mk_gap_input(f"gap-{i}") for i in range(3)]
    store = _mk_mock_store()
    embedder = _mk_mock_embedder()
    drafter = MockDrafter()

    draft_answers(
        gaps, store, embedder, drafter,
        top_k=5, mode="hybrid", min_supporting=1,
    )
    assert drafter.calls == 3
