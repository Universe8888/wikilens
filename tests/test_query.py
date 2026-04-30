"""Query module tests: RRF math (pure unit) + end-to-end integration."""

from __future__ import annotations

import pytest

from wikilens.embed import BGEEmbedder
from wikilens.pipeline import ingest_vault
from wikilens.query import RRF_K, _reciprocal_rank_fusion, query
from wikilens.rerank import BGEReranker
from wikilens.store import LanceDBStore, SearchHit

# --- RRF pure-math tests --------------------------------------------------


def _hit(cid: str) -> SearchHit:
    return SearchHit(
        chunk_id=cid,
        source_rel=f"{cid}.md",
        heading_path=(),
        text=f"text for {cid}",
        score=0.0,
    )


def test_rrf_empty_inputs():
    assert _reciprocal_rank_fusion([], []) == []


def test_rrf_single_retriever():
    hits = [_hit("a"), _hit("b"), _hit("c")]
    fused = _reciprocal_rank_fusion(hits, [])
    assert [h.chunk_id for h, _ in fused] == ["a", "b", "c"]
    # First entry should have highest RRF score
    assert fused[0][1] == pytest.approx(1 / (RRF_K + 1))
    assert fused[1][1] == pytest.approx(1 / (RRF_K + 2))


def test_rrf_agreement_boosts_rank():
    # Both retrievers agree 'a' is best; dense ranks 'b' second, bm25 ranks 'c' second
    dense = [_hit("a"), _hit("b"), _hit("c")]
    fts = [_hit("a"), _hit("c"), _hit("b")]
    fused = _reciprocal_rank_fusion(dense, fts)
    # 'a' appears at rank 1 in both → highest score
    assert fused[0][0].chunk_id == "a"
    # 'a' score should equal sum of 1/(k+1) from each list
    expected_a = 2 * (1 / (RRF_K + 1))
    assert fused[0][1] == pytest.approx(expected_a)


def test_rrf_missing_from_one_list_still_ranked():
    dense = [_hit("a"), _hit("b")]
    fts = [_hit("c"), _hit("d")]
    fused = _reciprocal_rank_fusion(dense, fts)
    ids = {h.chunk_id for h, _ in fused}
    assert ids == {"a", "b", "c", "d"}


# --- end-to-end integration (real BGE, LanceDB, reranker) -----------------


@pytest.fixture(scope="module")
def embedder() -> BGEEmbedder:
    e = BGEEmbedder()
    e._ensure_model()
    return e


@pytest.fixture(scope="module")
def reranker() -> BGEReranker:
    r = BGEReranker()
    r._ensure_model()
    return r


@pytest.fixture(scope="module")
def ingested(tmp_path_factory, embedder: BGEEmbedder):
    """A tiny ingested vault shared across query tests."""
    root = tmp_path_factory.mktemp("qvault")
    (root / "photo.md").write_text(
        "# Photosynthesis\n\nPlants convert sunlight, water, and carbon dioxide "
        "into glucose and oxygen using chlorophyll in chloroplasts.\n",
        encoding="utf-8",
    )
    (root / "resp.md").write_text(
        "# Cellular Respiration\n\nMitochondria turn glucose and oxygen into ATP, "
        "the cell's energy currency.\n",
        encoding="utf-8",
    )
    (root / "cat.md").write_text(
        "# Cats\n\nDomestic cats are small carnivorous mammals often kept as pets.\n",
        encoding="utf-8",
    )
    db = root / "db"
    ingest_vault(root, db_path=db, embedder=embedder)
    return {"root": root, "db": db}


def test_dense_mode_finds_relevant(ingested, embedder: BGEEmbedder):
    store = LanceDBStore(db_path=ingested["db"], dim=embedder.dim)
    results = query(
        "how do plants make food from sunlight",
        store=store,
        embedder=embedder,
        mode="dense",
        k=3,
    )
    assert len(results) >= 1
    assert "photo.md" in results[0].source_rel


def test_bm25_mode_finds_exact_keyword(ingested, embedder: BGEEmbedder):
    store = LanceDBStore(db_path=ingested["db"], dim=embedder.dim)
    results = query(
        "mitochondria",
        store=store,
        embedder=embedder,
        mode="bm25",
        k=3,
    )
    assert len(results) >= 1
    assert "resp.md" in results[0].source_rel


def test_hybrid_mode_returns_top_k(ingested, embedder: BGEEmbedder):
    store = LanceDBStore(db_path=ingested["db"], dim=embedder.dim)
    results = query(
        "what makes energy from glucose",
        store=store,
        embedder=embedder,
        mode="hybrid",
        k=2,
    )
    assert len(results) == 2
    # The cat note should not be in the top-2 for this query
    assert not any("cat.md" in r.source_rel for r in results)


def test_rerank_mode_requires_reranker(ingested, embedder: BGEEmbedder):
    store = LanceDBStore(db_path=ingested["db"], dim=embedder.dim)
    with pytest.raises(ValueError):
        query("anything", store=store, embedder=embedder, mode="rerank")


def test_rerank_mode_end_to_end(ingested, embedder: BGEEmbedder, reranker: BGEReranker):
    store = LanceDBStore(db_path=ingested["db"], dim=embedder.dim)
    results = query(
        "plants convert sunlight into sugar",
        store=store,
        embedder=embedder,
        mode="rerank",
        k=3,
        reranker=reranker,
    )
    assert len(results) >= 1
    assert "photo.md" in results[0].source_rel
    # Ranks must be 1..N
    assert [r.rank for r in results] == list(range(1, len(results) + 1))


def test_unknown_mode_raises(ingested, embedder: BGEEmbedder):
    store = LanceDBStore(db_path=ingested["db"], dim=embedder.dim)
    with pytest.raises(ValueError):
        query("x", store=store, embedder=embedder, mode="nonsense")  # type: ignore[arg-type]
