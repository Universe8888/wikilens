"""Tests for concepts.py + concept_judge.py — P9 Unnamed Concept Detector."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from wikilens.concept_judge import MockConceptJudge
from wikilens.concepts import ConceptFinding, ConceptProposal, detect_unnamed_concepts
from wikilens.gap import ChunkPoint, Cluster


def _point(chunk_id: str, source_rel: str, text: str = "body") -> ChunkPoint:
    return ChunkPoint(
        chunk_id=chunk_id,
        source_rel=source_rel,
        text=text,
        vector=np.zeros(2, dtype=np.float32),
    )


def _cluster(points: list[ChunkPoint], cluster_id: int = 0) -> Cluster:
    return Cluster(cluster_id=cluster_id, points=tuple(points))


# ---------------------------------------------------------------------------
# Frozen dataclasses
# ---------------------------------------------------------------------------


def test_concept_finding_frozen():
    finding = ConceptFinding(
        cluster_id=0,
        proposed_term="ontology",
        confidence=0.8,
        rationale="test",
        supporting_notes=["a.md"],
        evidence_chunks=["c1"],
        term_freq_in_cluster=0.0,
    )
    with pytest.raises((AttributeError, TypeError)):
        finding.proposed_term = "other"  # type: ignore[misc]


def test_concept_proposal_frozen():
    proposal = ConceptProposal(
        proposed_term="emergence",
        confidence=0.7,
        rationale="test",
    )
    with pytest.raises((AttributeError, TypeError)):
        proposal.proposed_term = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# MockConceptJudge
# ---------------------------------------------------------------------------


def test_mock_judge_returns_proposal():
    pts = [_point("c1", "a.md"), _point("c2", "b.md")]
    proposal = MockConceptJudge().propose(pts)
    assert isinstance(proposal, ConceptProposal)
    assert proposal.proposed_term != ""


def test_mock_judge_deterministic():
    pts = [_point("c1", "a.md"), _point("c2", "b.md")]
    judge = MockConceptJudge()
    p1 = judge.propose(pts)
    p2 = judge.propose(pts)
    assert p1 == p2


# ---------------------------------------------------------------------------
# term_freq_in_cluster logic (exercised via detect_unnamed_concepts)
# The easiest way to test freq calculation is to drive through the pipeline
# with a patched cluster_chunks so we control exactly what clusters are seen.
# ---------------------------------------------------------------------------


def _fake_store() -> MagicMock:
    table = MagicMock()
    arrow = MagicMock()
    arrow.to_pylist.return_value = []
    table.to_arrow.return_value = arrow
    store = MagicMock()
    store._get_or_create_table.return_value = table
    return store


def test_term_freq_absent(tmp_path):
    pts = [
        _point("c0", "a.md", "unrelated text"),
        _point("c1", "b.md", "something else"),
        _point("c2", "c.md", "no match here"),
    ]
    cluster = _cluster(pts, cluster_id=7)

    with patch("wikilens.concepts._iter_all_points", return_value=pts), \
         patch("wikilens.concepts.cluster_chunks", return_value=[cluster]):
        findings = detect_unnamed_concepts(
            str(tmp_path / "db"),
            "chunks",
            MockConceptJudge(),
            absence_threshold=0.20,
        )

    assert len(findings) == 1
    assert findings[0].term_freq_in_cluster == 0.0


def test_term_freq_present(tmp_path):
    term = "mock_concept"
    pts = [
        _point("c0", "a.md", f"discussion about {term}"),
        _point("c1", "b.md", f"the {term} is important"),
        _point("c2", "c.md", "mock_concept appears here"),
    ]
    cluster = _cluster(pts, cluster_id=3)

    with patch("wikilens.concepts._iter_all_points", return_value=pts), \
         patch("wikilens.concepts.cluster_chunks", return_value=[cluster]):
        findings = detect_unnamed_concepts(
            str(tmp_path / "db"),
            "chunks",
            MockConceptJudge(),
            absence_threshold=1.1,
        )

    assert len(findings) == 1
    assert findings[0].term_freq_in_cluster == 1.0


# ---------------------------------------------------------------------------
# Absence filter
# ---------------------------------------------------------------------------


def test_absence_filter_excludes_named(tmp_path):
    pts = [
        _point("c0", "a.md", "mock_concept everywhere"),
        _point("c1", "b.md", "mock_concept again"),
        _point("c2", "c.md", "mock_concept here too"),
        _point("c3", "d.md", "unrelated text"),
        _point("c4", "e.md", "more unrelated"),
    ]
    cluster = _cluster(pts, cluster_id=1)

    with patch("wikilens.concepts._iter_all_points", return_value=pts), \
         patch("wikilens.concepts.cluster_chunks", return_value=[cluster]):
        findings = detect_unnamed_concepts(
            str(tmp_path / "db"),
            "chunks",
            MockConceptJudge(),
            absence_threshold=0.20,
        )

    assert findings == []


def test_absence_filter_includes_unnamed(tmp_path):
    pts = [
        _point("c0", "a.md", "no mention of the term"),
        _point("c1", "b.md", "also unrelated"),
        _point("c2", "c.md", "still nothing"),
        _point("c3", "d.md", "blank content"),
        _point("c4", "e.md", "irrelevant"),
    ]
    cluster = _cluster(pts, cluster_id=2)

    with patch("wikilens.concepts._iter_all_points", return_value=pts), \
         patch("wikilens.concepts.cluster_chunks", return_value=[cluster]):
        findings = detect_unnamed_concepts(
            str(tmp_path / "db"),
            "chunks",
            MockConceptJudge(),
            absence_threshold=0.20,
        )

    assert len(findings) == 1
    assert findings[0].term_freq_in_cluster < 0.20


# ---------------------------------------------------------------------------
# Empty DB
# ---------------------------------------------------------------------------


def test_detect_unnamed_concepts_empty_db(tmp_path):
    with patch("wikilens.concepts._iter_all_points", return_value=[]), \
         patch("wikilens.concepts.cluster_chunks", return_value=[]):
        findings = detect_unnamed_concepts(
            str(tmp_path / "db"),
            "chunks",
            MockConceptJudge(),
        )

    assert findings == []
