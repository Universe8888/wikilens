"""Tests for contradiction candidate pair generation + filters (P4, Phase 4.1).

Unit-tests hit the filter logic directly with synthetic ChunkRefs and vector
maps — no LanceDB, no embedder. The end-to-end CLI path is covered by
``tests/test_contradict_cli.py`` against a tiny real ingest.
"""

from __future__ import annotations

import numpy as np

from wikilens.contradict import (
    CandidatePair,
    ChunkRef,
    _canonical,
    filter_pairs,
)


def _ref(chunk_id: str, source_rel: str, text: str = "body") -> ChunkRef:
    return ChunkRef(
        chunk_id=chunk_id, source_rel=source_rel, heading_path=(), text=text
    )


def test_canonical_orders_pair_by_chunk_id():
    a = _ref("z1", "a.md")
    b = _ref("a1", "b.md")
    p = _canonical(a, b, retrieval_score=0.7)
    assert p.a.chunk_id == "a1"
    assert p.b.chunk_id == "z1"


def test_canonical_preserves_already_ordered():
    a = _ref("a1", "a.md")
    b = _ref("b1", "b.md")
    p = _canonical(a, b, retrieval_score=0.7)
    assert (p.a.chunk_id, p.b.chunk_id) == ("a1", "b1")


def test_filter_drops_same_note_pairs():
    a = _ref("c1", "note.md")
    b = _ref("c2", "note.md")
    pair = CandidatePair(a=a, b=b, retrieval_score=0.9)
    assert filter_pairs([pair]) == []


def test_filter_keeps_cross_note_pairs():
    a = _ref("c1", "a.md")
    b = _ref("c2", "b.md")
    pair = CandidatePair(a=a, b=b, retrieval_score=0.9)
    assert filter_pairs([pair]) == [pair]


def test_filter_dedupes_symmetric_pairs():
    a = _ref("c1", "a.md")
    b = _ref("c2", "b.md")
    # Same canonical pair fed twice — from A querying B, and B querying A.
    # retrieval_score differs by direction; filter dedups on (id_a, id_b).
    p1 = _canonical(a, b, retrieval_score=0.9)
    p2 = _canonical(b, a, retrieval_score=0.8)
    assert (p1.a.chunk_id, p1.b.chunk_id) == (p2.a.chunk_id, p2.b.chunk_id)
    out = filter_pairs([p1, p2])
    assert len(out) == 1


def test_filter_drops_near_duplicates_above_threshold():
    a = _ref("c1", "a.md")
    b = _ref("c2", "b.md")
    pair = CandidatePair(a=a, b=b, retrieval_score=0.9)
    v = np.array([1.0, 0.0], dtype=np.float32)
    # Cosine = 1.0 > 0.95 → dropped as near-duplicate.
    out = filter_pairs([pair], vectors={"c1": v, "c2": v}, dup_threshold=0.95)
    assert out == []


def test_filter_keeps_dissimilar_pairs_under_threshold():
    a = _ref("c1", "a.md")
    b = _ref("c2", "b.md")
    pair = CandidatePair(a=a, b=b, retrieval_score=0.9)
    va = np.array([1.0, 0.0], dtype=np.float32)
    vb = np.array([0.0, 1.0], dtype=np.float32)  # cosine = 0.0
    out = filter_pairs([pair], vectors={"c1": va, "c2": vb}, dup_threshold=0.95)
    assert out == [pair]


def test_filter_skips_near_dup_check_when_vectors_missing():
    # Vector map doesn't include these IDs — filter falls through to keep.
    a = _ref("missing_a", "a.md")
    b = _ref("missing_b", "b.md")
    pair = CandidatePair(a=a, b=b, retrieval_score=0.5)
    v = np.array([1.0, 0.0], dtype=np.float32)
    out = filter_pairs([pair], vectors={"other": v}, dup_threshold=0.95)
    assert out == [pair]


def test_filter_preserves_input_ordering_of_distinct_pairs():
    pairs = [
        _canonical(_ref("a1", "n1.md"), _ref("b1", "n2.md"), retrieval_score=0.5),
        _canonical(_ref("a2", "n3.md"), _ref("b2", "n4.md"), retrieval_score=0.5),
    ]
    out = filter_pairs(pairs)
    assert [p.a.chunk_id for p in out] == ["a1", "a2"]
