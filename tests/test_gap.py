"""Tests for gap.py — clustering + generate_gaps pipeline (P5, Phase 5.1).

Unit tests hit ``cluster_chunks`` directly with synthetic 2-D vectors.
The end-to-end pipeline is exercised with a ``MockGenerator`` and a
fake store so sklearn + LanceDB dependencies stay out of the unit-test
fast path.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np

from wikilens.gap import (
    ChunkPoint,
    Cluster,
    _default_k,
    cluster_chunks,
    generate_gaps,
)
from wikilens.generator import GapCandidate, MockGenerator


def _point(chunk_id: str, source_rel: str, vec: list[float], text: str = "body") -> ChunkPoint:
    return ChunkPoint(
        chunk_id=chunk_id,
        source_rel=source_rel,
        text=text,
        vector=np.asarray(vec, dtype=np.float32),
    )


def test_default_k_handles_small_vault():
    # n<4 is a degenerate branch — cluster_chunks() short-circuits before
    # _default_k is called, so we only assert sensible behaviour for n>=1.
    assert _default_k(1) == 1
    assert _default_k(3) == 3
    # sqrt(4)=2, sqrt(16)=4, sqrt(100)=10.
    assert _default_k(4) == 2
    assert _default_k(16) == 4
    assert _default_k(100) == 10


def test_cluster_chunks_empty_input_returns_empty():
    assert cluster_chunks([]) == []


def test_cluster_chunks_below_min_returns_empty():
    pts = [_point("a", "a.md", [1.0, 0.0]), _point("b", "b.md", [1.0, 0.1])]
    # min_cluster_size=3 with only 2 points → empty.
    assert cluster_chunks(pts, min_cluster_size=3) == []


def test_cluster_chunks_separates_three_gaussian_blobs():
    # Three well-separated clusters of 4 points each.
    blob_a = [_point(f"a{i}", "a.md", [0.0 + 0.01 * i, 0.0]) for i in range(4)]
    blob_b = [_point(f"b{i}", "b.md", [5.0 + 0.01 * i, 5.0]) for i in range(4)]
    blob_c = [_point(f"c{i}", "c.md", [-5.0 + 0.01 * i, 5.0]) for i in range(4)]

    clusters = cluster_chunks(
        blob_a + blob_b + blob_c,
        k=3,
        min_cluster_size=3,
        max_clusters=10,
    )
    assert len(clusters) == 3
    # Each returned cluster must be a pure blob (all IDs share prefix).
    for c in clusters:
        prefixes = {p.chunk_id[0] for p in c.points}
        assert len(prefixes) == 1, f"cluster mixed blobs: {c.points}"
        assert c.size == 4


def test_cluster_chunks_drops_clusters_below_min_size():
    # Two large blobs + one lone point that will end up in a singleton cluster.
    blob_a = [_point(f"a{i}", "a.md", [0.0 + 0.01 * i, 0.0]) for i in range(5)]
    blob_b = [_point(f"b{i}", "b.md", [5.0 + 0.01 * i, 5.0]) for i in range(5)]
    lone = [_point("z0", "z.md", [-10.0, -10.0])]

    clusters = cluster_chunks(
        blob_a + blob_b + lone,
        k=3,
        min_cluster_size=3,
    )
    # Lone point's singleton cluster dropped; two real clusters remain.
    assert len(clusters) == 2
    for c in clusters:
        assert c.size >= 3
        assert all(p.chunk_id != "z0" for p in c.points)


def test_cluster_chunks_applies_max_clusters_cap():
    # Four well-separated blobs, but cap at 2.
    blobs = []
    for i, center in enumerate([(0, 0), (10, 10), (-10, 10), (10, -10)]):
        blobs.extend(
            [_point(f"{chr(ord('a') + i)}{j}", f"{i}.md", [center[0] + 0.01 * j, center[1]])
             for j in range(3)]
        )
    clusters = cluster_chunks(blobs, k=4, min_cluster_size=3, max_clusters=2)
    assert len(clusters) == 2


def test_cluster_chunks_is_deterministic_under_seed():
    blob_a = [_point(f"a{i}", "a.md", [0.0 + 0.01 * i, 0.0]) for i in range(4)]
    blob_b = [_point(f"b{i}", "b.md", [5.0 + 0.01 * i, 5.0]) for i in range(4)]
    pts = blob_a + blob_b

    c1 = cluster_chunks(pts, k=2, seed=42, min_cluster_size=3)
    c2 = cluster_chunks(pts, k=2, seed=42, min_cluster_size=3)
    # Same seed, same input → identical cluster shapes (ids within each cluster).
    assert [tuple(p.chunk_id for p in c.points) for c in c1] == \
           [tuple(p.chunk_id for p in c.points) for c in c2]


def test_cluster_chunks_sorts_largest_first():
    big = [_point(f"a{i}", "a.md", [0.0 + 0.01 * i, 0.0]) for i in range(6)]
    small = [_point(f"b{i}", "b.md", [5.0 + 0.01 * i, 5.0]) for i in range(3)]

    clusters = cluster_chunks(big + small, k=2, min_cluster_size=3)
    assert clusters[0].size >= clusters[1].size


# ---------------------------------------------------------------------------
# generate_gaps pipeline — uses a fake VectorStore and MockGenerator.
# ---------------------------------------------------------------------------


def _fake_store(rows: list[dict]) -> MagicMock:
    """Build a VectorStore-shaped mock that yields the given rows on full scan."""
    table = MagicMock()
    arrow = MagicMock()
    arrow.to_pylist.return_value = rows
    table.to_arrow.return_value = arrow
    store = MagicMock()
    store._get_or_create_table.return_value = table
    return store


def test_generate_gaps_returns_empty_on_empty_store():
    store = _fake_store([])
    gen = MockGenerator()
    clusters, findings = generate_gaps(store, gen, min_cluster_size=3)
    assert clusters == []
    assert findings == []
    assert gen.calls == 0


def test_generate_gaps_calls_generator_once_per_cluster():
    # Two separable blobs of 3 points each.
    rows = []
    for i in range(3):
        rows.append({
            "chunk_id": f"a{i}",
            "source_rel": "a.md",
            "text": f"biology content {i}",
            "vector": [0.0 + 0.01 * i, 0.0],
        })
    for i in range(3):
        rows.append({
            "chunk_id": f"b{i}",
            "source_rel": "b.md",
            "text": f"physics content {i}",
            "vector": [5.0 + 0.01 * i, 5.0],
        })

    store = _fake_store(rows)
    gen = MockGenerator()
    clusters, findings = generate_gaps(
        store, gen, k=2, min_cluster_size=3, top_gaps_per_cluster=1
    )
    assert len(clusters) == 2
    assert gen.calls == 2
    assert len(findings) == 2
    # Every finding carries the correct cluster_id/size.
    for f in findings:
        assert f.cluster_size == 3


def test_generate_gaps_respects_top_gaps_per_cluster():
    rows = [
        {"chunk_id": f"c{i}", "source_rel": "c.md", "text": "t", "vector": [0.0, 0.0 + 0.01 * i]}
        for i in range(4)
    ]
    seeded = [[
        GapCandidate(gap_question="q1?", suggested_note_title="a", rationale="r"),
        GapCandidate(gap_question="q2?", suggested_note_title="b", rationale="r"),
        GapCandidate(gap_question="q3?", suggested_note_title="c", rationale="r"),
    ]]
    store = _fake_store(rows)
    gen = MockGenerator(candidates=seeded)
    clusters, findings = generate_gaps(
        store, gen, k=1, min_cluster_size=3, top_gaps_per_cluster=2
    )
    assert len(clusters) == 1
    assert len(findings) == 2
    assert [f.candidate.suggested_note_title for f in findings] == ["a", "b"]


def test_generate_gaps_respects_sample_cap():
    # Three clusters; sample=1 → only the largest is processed.
    rows = []
    blobs = [("big", "a", (0, 0)), ("mid", "b", (5, 5)), ("mid", "c", (-5, 5))]
    for label, prefix, center in blobs:
        size = 5 if label == "big" else 3
        for i in range(size):
            rows.append({
                "chunk_id": f"{prefix}{i}",
                "source_rel": f"{prefix}.md",
                "text": f"{label} {i}",
                "vector": [center[0] + 0.01 * i, center[1]],
            })

    store = _fake_store(rows)
    gen = MockGenerator()
    clusters, findings = generate_gaps(
        store, gen, k=3, min_cluster_size=3, top_gaps_per_cluster=1, sample=1
    )
    assert len(clusters) == 3  # all clusters returned
    assert gen.calls == 1      # but only one was invoked
    assert len(findings) == 1


def test_generate_gaps_skips_rows_with_missing_vectors():
    rows = [
        {"chunk_id": "a1", "source_rel": "a.md", "text": "t", "vector": [0.0, 0.0]},
        {"chunk_id": "a2", "source_rel": "a.md", "text": "t", "vector": None},
        {"chunk_id": "a3", "source_rel": "a.md", "text": "t", "vector": [0.1, 0.1]},
        {"chunk_id": "a4", "source_rel": "a.md", "text": "t", "vector": [0.2, 0.2]},
    ]
    store = _fake_store(rows)
    gen = MockGenerator()
    clusters, findings = generate_gaps(
        store, gen, k=1, min_cluster_size=3, top_gaps_per_cluster=1
    )
    # 3 valid points after skipping None vector; min_cluster_size=3 → one cluster.
    assert len(clusters) == 1
    assert clusters[0].size == 3


def test_cluster_dataclass_size_property():
    pts = (_point("a", "a.md", [0.0, 0.0]), _point("b", "b.md", [0.0, 0.0]))
    c = Cluster(cluster_id=1, points=pts)
    assert c.size == 2
