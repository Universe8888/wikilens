"""Query-time orchestration: dense, BM25, RRF fusion, and reranking.

Four retrieval modes, all returning a uniform `list[QueryResult]`:

- `dense`: pure vector cosine search
- `bm25`: pure FTS / BM25 search
- `hybrid`: RRF fusion of dense top-N + BM25 top-N
- `rerank`: `hybrid` top-M, then cross-encoder rerank to top-k

Fusion uses reciprocal-rank fusion (Cormack et al. 2009) with k=60.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from wikilens.embed import Embedder
from wikilens.rerank import Reranker
from wikilens.store import SearchHit, VectorStore

Mode = Literal["dense", "bm25", "hybrid", "rerank"]

RRF_K = 60  # canonical constant from Cormack et al. 2009
HYBRID_CANDIDATES_PER_RETRIEVER = 50
RERANK_CANDIDATES = 20


@dataclass(frozen=True)
class QueryResult:
    """One retrieval result, ranked."""

    rank: int  # 1-based
    chunk_id: str
    source_rel: str
    heading_path: tuple[str, ...]
    text: str
    score: float  # interpretation depends on mode


def _reciprocal_rank_fusion(
    dense_hits: list[SearchHit],
    fts_hits: list[SearchHit],
    k: int = RRF_K,
) -> list[tuple[SearchHit, float]]:
    """Combine two ranked lists into one via RRF.

    RRF is score-agnostic — it cares only about the RANK of each item in
    each list. That's exactly what we need: cosine and BM25 are on
    incomparable scales.

    Returns list of (hit, rrf_score) sorted descending by rrf_score.
    Ties are broken by rank-1 appearance in the dense list.
    """
    scores: dict[str, float] = {}
    hit_by_id: dict[str, SearchHit] = {}

    for rank, hit in enumerate(dense_hits, start=1):
        scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + 1.0 / (k + rank)
        hit_by_id.setdefault(hit.chunk_id, hit)

    for rank, hit in enumerate(fts_hits, start=1):
        scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + 1.0 / (k + rank)
        hit_by_id.setdefault(hit.chunk_id, hit)

    fused = [(hit_by_id[cid], s) for cid, s in scores.items()]
    fused.sort(key=lambda x: x[1], reverse=True)
    return fused


def _hits_to_results(hits: list[SearchHit], scores: list[float] | None = None) -> list[QueryResult]:
    out: list[QueryResult] = []
    for i, h in enumerate(hits):
        out.append(
            QueryResult(
                rank=i + 1,
                chunk_id=h.chunk_id,
                source_rel=h.source_rel,
                heading_path=h.heading_path,
                text=h.text,
                score=scores[i] if scores is not None else h.score,
            )
        )
    return out


def query(
    question: str,
    *,
    store: VectorStore,
    embedder: Embedder,
    mode: Mode = "rerank",
    k: int = 5,
    reranker: Reranker | None = None,
    hybrid_candidates: int = HYBRID_CANDIDATES_PER_RETRIEVER,
    rerank_candidates: int = RERANK_CANDIDATES,
) -> list[QueryResult]:
    """Run a query against the store in the given mode.

    For `mode="rerank"`, `reranker` must be provided (caller owns model lifecycle).
    """
    if mode == "dense":
        q_vec = embedder.encode_query(question)
        hits = store.search_dense(q_vec, k=k)
        return _hits_to_results(hits)

    if mode == "bm25":
        hits = store.search_fts(question, k=k)
        return _hits_to_results(hits)

    # Hybrid path — shared by `hybrid` and `rerank`
    q_vec = embedder.encode_query(question)
    dense_hits = store.search_dense(q_vec, k=hybrid_candidates)
    fts_hits = store.search_fts(question, k=hybrid_candidates)
    fused = _reciprocal_rank_fusion(dense_hits, fts_hits)

    if mode == "hybrid":
        top = fused[:k]
        return [
            QueryResult(
                rank=i + 1,
                chunk_id=hit.chunk_id,
                source_rel=hit.source_rel,
                heading_path=hit.heading_path,
                text=hit.text,
                score=score,
            )
            for i, (hit, score) in enumerate(top)
        ]

    if mode == "rerank":
        if reranker is None:
            raise ValueError("mode='rerank' requires a Reranker instance")
        candidates = fused[:rerank_candidates]
        if not candidates:
            return []
        hits_only = [h for h, _ in candidates]
        rerank_scores = reranker.score(question, [h.text for h in hits_only])
        # Sort by rerank score descending, keep top-k
        paired = sorted(
            zip(hits_only, rerank_scores, strict=True),
            key=lambda x: x[1],
            reverse=True,
        )[:k]
        return [
            QueryResult(
                rank=i + 1,
                chunk_id=hit.chunk_id,
                source_rel=hit.source_rel,
                heading_path=hit.heading_path,
                text=hit.text,
                score=score,
            )
            for i, (hit, score) in enumerate(paired)
        ]

    raise ValueError(f"unknown mode: {mode}")
