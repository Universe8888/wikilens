"""Vector store tests — real LanceDB backend on tmp_path."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from wikilens.ingest import Chunk
from wikilens.store import LanceDBStore, SearchHit, VectorStore


def _chunk(cid: str, text: str, path: str = "note.md") -> Chunk:
    return Chunk(
        chunk_id=cid,
        source_path=Path(path),
        source_rel=path,
        heading_path=("H",),
        text=text,
        token_count=len(text.split()),
        char_start=0,
        char_end=len(text),
        chunk_index=0,
        content_hash=cid,
        frontmatter={},
    )


def _vec(seed: int, dim: int = 8) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(dim).astype(np.float32)
    v /= np.linalg.norm(v)
    return v


@pytest.fixture
def store(tmp_path: Path) -> LanceDBStore:
    return LanceDBStore(db_path=tmp_path / "db", dim=8)


def test_lancedb_implements_protocol(store: LanceDBStore):
    assert isinstance(store, VectorStore)


def test_empty_store_count_zero(store: LanceDBStore):
    assert store.count() == 0


def test_empty_store_search_returns_empty(store: LanceDBStore):
    assert store.search_dense(_vec(0), k=5) == []
    assert store.search_fts("anything", k=5) == []


def test_upsert_inserts_and_counts(store: LanceDBStore):
    chunks = [_chunk("a", "first"), _chunk("b", "second")]
    vecs = np.stack([_vec(1), _vec(2)])
    n = store.upsert(chunks, vecs)
    assert n == 2
    assert store.count() == 2


def test_upsert_replaces_existing_chunk_id(store: LanceDBStore):
    chunks1 = [_chunk("a", "original")]
    store.upsert(chunks1, np.stack([_vec(1)]))

    chunks2 = [_chunk("a", "updated")]
    store.upsert(chunks2, np.stack([_vec(2)]))

    assert store.count() == 1
    hits = store.search_dense(_vec(2), k=1)
    assert hits[0].text == "updated"


def test_upsert_rejects_length_mismatch(store: LanceDBStore):
    with pytest.raises(ValueError):
        store.upsert([_chunk("a", "x")], np.stack([_vec(1), _vec(2)]))


def test_dense_search_returns_nearest(store: LanceDBStore):
    target = _vec(42)
    far = -target  # opposite direction → cosine similarity = -1
    store.upsert(
        [_chunk("near", "the nearest"), _chunk("far", "the farthest")],
        np.stack([target, far]),
    )
    hits = store.search_dense(target, k=2)
    assert len(hits) == 2
    assert hits[0].chunk_id == "near"
    assert hits[0].score > hits[1].score
    assert hits[0].score == pytest.approx(1.0, abs=1e-4)


def test_dense_search_respects_k(store: LanceDBStore):
    chunks = [_chunk(f"c{i}", f"text {i}") for i in range(5)]
    vecs = np.stack([_vec(i) for i in range(5)])
    store.upsert(chunks, vecs)
    assert len(store.search_dense(_vec(0), k=3)) == 3


def test_fts_search_finds_keyword(store: LanceDBStore):
    chunks = [
        _chunk("a", "photosynthesis converts light into glucose"),
        _chunk("b", "respiration converts glucose into atp"),
        _chunk("c", "unrelated content about cats"),
    ]
    vecs = np.stack([_vec(i) for i in range(3)])
    store.upsert(chunks, vecs)
    hits = store.search_fts("photosynthesis", k=3)
    assert len(hits) >= 1
    assert hits[0].chunk_id == "a"


def test_fts_handles_empty_query_gracefully(store: LanceDBStore):
    store.upsert([_chunk("a", "some text")], np.stack([_vec(0)]))
    # Empty or malformed FTS queries must not crash
    hits = store.search_fts("", k=5)
    assert isinstance(hits, list)


def test_search_hit_preserves_metadata(store: LanceDBStore):
    c = Chunk(
        chunk_id="x",
        source_path=Path("notes/bio.md"),
        source_rel="notes/bio.md",
        heading_path=("Biology", "Photosynthesis"),
        text="plants turn light into sugar",
        token_count=5,
        char_start=10,
        char_end=45,
        chunk_index=3,
        content_hash="x",
        frontmatter={},
    )
    store.upsert([c], np.stack([_vec(0)]))
    hits = store.search_dense(_vec(0), k=1)
    assert isinstance(hits[0], SearchHit)
    assert hits[0].source_rel == "notes/bio.md"
    assert hits[0].heading_path == ("Biology", "Photosynthesis")


def test_reopen_same_db_path_keeps_data(tmp_path: Path):
    db_path = tmp_path / "db"
    s1 = LanceDBStore(db_path, dim=8)
    s1.upsert([_chunk("a", "hello")], np.stack([_vec(0)]))
    assert s1.count() == 1

    s2 = LanceDBStore(db_path, dim=8)
    assert s2.count() == 1
