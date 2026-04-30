"""Tests for the Generator protocol, GapCandidate, and MockGenerator (P5).

No real API calls. ClaudeGenerator tests land in Phase 5.2 with a
monkeypatched Anthropic client.
"""

from __future__ import annotations

import pytest

from wikilens.generator import (
    GapCandidate,
    GapFinding,
    Generator,
    MockGenerator,
)


def test_gap_candidate_accepts_valid_shape():
    c = GapCandidate(
        gap_question="What is X?",
        suggested_note_title="what-is-x",
        rationale="three notes mention X but none define it",
        supporting_chunk_ids=("c1", "c2", "c3"),
    )
    assert c.gap_question == "What is X?"
    assert c.suggested_note_title == "what-is-x"


def test_gap_candidate_rejects_empty_question():
    with pytest.raises(ValueError, match="gap_question"):
        GapCandidate(
            gap_question="   ",
            suggested_note_title="stub",
            rationale="r",
        )


def test_gap_candidate_rejects_empty_title():
    with pytest.raises(ValueError, match="suggested_note_title"):
        GapCandidate(
            gap_question="q?",
            suggested_note_title="",
            rationale="r",
        )


def test_gap_candidate_rejects_non_kebab_title():
    for bad in ["Not Kebab", "with_underscore", "UPPER", "has space", "-leading", "trailing-"]:
        with pytest.raises(ValueError, match="kebab-case"):
            GapCandidate(
                gap_question="q?",
                suggested_note_title=bad,
                rationale="r",
            )


def test_gap_candidate_accepts_kebab_with_digits():
    c = GapCandidate(
        gap_question="q?",
        suggested_note_title="python-3-asyncio",
        rationale="r",
    )
    assert c.suggested_note_title == "python-3-asyncio"


def test_gap_finding_binds_cluster_metadata():
    c = GapCandidate(gap_question="q?", suggested_note_title="s", rationale="r")
    f = GapFinding(cluster_id=3, cluster_size=7, candidate=c)
    assert f.cluster_id == 3
    assert f.cluster_size == 7
    assert f.candidate is c


def test_mock_generator_default_returns_single_gap():
    g = MockGenerator()
    out = g.propose_gaps([("c1", "text 1"), ("c2", "text 2")], top_k=3)
    assert len(out) == 1
    assert out[0].suggested_note_title == "mock-gap-1"
    assert out[0].supporting_chunk_ids == ("c1", "c2")
    assert g.calls == 1


def test_mock_generator_default_respects_top_k():
    g = MockGenerator()
    # Default returns one candidate, so top_k=0 should truncate to empty.
    out = g.propose_gaps([("c1", "x")], top_k=0)
    assert out == []


def test_mock_generator_cycles_seeded_batches():
    batches = [
        [
            GapCandidate(gap_question="q1?", suggested_note_title="a", rationale="r1"),
            GapCandidate(gap_question="q2?", suggested_note_title="b", rationale="r2"),
        ],
        [
            GapCandidate(gap_question="q3?", suggested_note_title="c", rationale="r3"),
        ],
    ]
    g = MockGenerator(candidates=batches)
    call1 = g.propose_gaps([("x", "t")], top_k=5)
    call2 = g.propose_gaps([("x", "t")], top_k=5)
    call3 = g.propose_gaps([("x", "t")], top_k=5)  # cycles back to batch[0]
    assert [c.suggested_note_title for c in call1] == ["a", "b"]
    assert [c.suggested_note_title for c in call2] == ["c"]
    assert [c.suggested_note_title for c in call3] == ["a", "b"]
    assert g.calls == 3


def test_mock_generator_truncates_seeded_batch_to_top_k():
    batch = [
        GapCandidate(gap_question="q1?", suggested_note_title="a", rationale="r"),
        GapCandidate(gap_question="q2?", suggested_note_title="b", rationale="r"),
        GapCandidate(gap_question="q3?", suggested_note_title="c", rationale="r"),
    ]
    g = MockGenerator(candidates=[batch])
    out = g.propose_gaps([("x", "t")], top_k=2)
    assert [c.suggested_note_title for c in out] == ["a", "b"]


def test_mock_generator_conforms_to_generator_protocol():
    g = MockGenerator()
    assert isinstance(g, Generator)
    assert g.name == "mock"
