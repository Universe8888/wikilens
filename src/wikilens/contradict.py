"""Contradiction Finder — candidate pair generation (P4).

Uses P2 hybrid retrieval to surface chunk pairs that share topic space and
might contradict. Three filters in one place:

1. Same-note dedup — pairs within the same source note are not
   contradictions we care about (internal consistency is an author
   concern, not a cross-vault concern).
2. Canonical ordering — each unordered pair ``{A, B}`` appears at most
   once, with ``chunk_id_a < chunk_id_b``.
3. Near-duplicate dedup — pairs whose chunk texts are near-identical
   (cosine > ``DEFAULT_DUP_THRESHOLD``) are dropped as likely copies
   rather than contradictions.

The judge runs over the resulting ``CandidatePair`` list. This module
owns no LLM and no network — it's pure retrieval + filtering.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np

from wikilens.embed import BGEEmbedder, Embedder
from wikilens.query import query
from wikilens.store import SearchHit, VectorStore

DEFAULT_TOP_K = 10
DEFAULT_DUP_THRESHOLD = 0.95


@dataclass(frozen=True)
class ChunkRef:
    """Minimal chunk identity for pair generation.

    ``source_rel`` drives same-note dedup; ``chunk_id`` drives canonical
    ordering and pair uniqueness; ``text`` is what the judge sees;
    ``heading_path`` is carried along for display only.
    """

    chunk_id: str
    source_rel: str
    heading_path: tuple[str, ...]
    text: str


@dataclass(frozen=True)
class CandidatePair:
    """An ordered pair (a, b) with ``a.chunk_id < b.chunk_id``.

    ``retrieval_score`` is whatever the upstream retriever reported for
    ``b`` when ``a.text`` was the query — useful for downstream
    thresholding or debugging, but the judge ignores it.
    """

    a: ChunkRef
    b: ChunkRef
    retrieval_score: float


def _hit_to_ref(hit: SearchHit) -> ChunkRef:
    return ChunkRef(
        chunk_id=hit.chunk_id,
        source_rel=hit.source_rel,
        heading_path=hit.heading_path,
        text=hit.text,
    )


def _canonical(a: ChunkRef, b: ChunkRef, retrieval_score: float) -> CandidatePair:
    """Order a, b so that ``chunk_id_a < chunk_id_b``. Stable dedup key."""
    if a.chunk_id < b.chunk_id:
        return CandidatePair(a=a, b=b, retrieval_score=retrieval_score)
    return CandidatePair(a=b, b=a, retrieval_score=retrieval_score)


def _iter_all_chunks(store: VectorStore) -> list[ChunkRef]:
    """Pull every chunk from the store as a ChunkRef.

    LanceDB-specific: uses ``_table.to_list()`` which is O(n) on table
    size. For P4's target vault sizes (tens of thousands of chunks this
    is fine. Swapping this for a paged scan is a Phase 4.5+ concern.
    """
    # The VectorStore protocol doesn't expose "iter all rows" — we
    # reach into the LanceDB backend directly. Acceptable because P4
    # only ships with LanceDB as a backend (same as P2/P3).
    table = store._get_or_create_table()  # type: ignore[attr-defined]
    rows = table.to_arrow().to_pylist()
    out: list[ChunkRef] = []
    for row in rows:
        heading = row.get("heading_path") or ""
        hp = tuple(s for s in heading.split(" > ") if s) if heading else ()
        out.append(
            ChunkRef(
                chunk_id=row["chunk_id"],
                source_rel=row["source_rel"],
                heading_path=hp,
                text=row["text"],
            )
        )
    return out


def _filter_same_note(pair: CandidatePair) -> bool:
    """True iff the pair survives the same-note filter (different sources)."""
    return pair.a.source_rel != pair.b.source_rel


def _filter_near_duplicate(
    pair: CandidatePair,
    vectors: dict[str, np.ndarray] | None,
    threshold: float,
) -> bool:
    """True iff the pair survives the near-duplicate filter.

    If no vector map is supplied, we skip this filter (used by unit
    tests that don't care about dedup). Embeddings are L2-normalized
    by BGEEmbedder, so cosine == dot product.
    """
    if vectors is None:
        return True
    va = vectors.get(pair.a.chunk_id)
    vb = vectors.get(pair.b.chunk_id)
    if va is None or vb is None:
        return True
    cosine = float(np.dot(va, vb))
    return cosine <= threshold


def filter_pairs(
    pairs: Iterable[CandidatePair],
    *,
    vectors: dict[str, np.ndarray] | None = None,
    dup_threshold: float = DEFAULT_DUP_THRESHOLD,
) -> list[CandidatePair]:
    """Apply same-note + canonical + near-dup filters.

    Canonical ordering is assumed to already be in place (callers
    produce pairs via ``_canonical``); this function dedupes by the
    ``(chunk_id_a, chunk_id_b)`` key to guard against accidental
    double-generation from retrieval symmetry (A returns B as a
    neighbor, then B returns A, producing the same pair twice).
    """
    seen: set[tuple[str, str]] = set()
    out: list[CandidatePair] = []
    for p in pairs:
        if not _filter_same_note(p):
            continue
        key = (p.a.chunk_id, p.b.chunk_id)
        if key in seen:
            continue
        if not _filter_near_duplicate(p, vectors, dup_threshold):
            continue
        seen.add(key)
        out.append(p)
    return out


def generate_candidate_pairs(
    store: VectorStore,
    *,
    embedder: Embedder | None = None,
    top_k: int = DEFAULT_TOP_K,
    dup_threshold: float = DEFAULT_DUP_THRESHOLD,
) -> list[CandidatePair]:
    """Walk every chunk in the store, hybrid-retrieve its top-k neighbors,
    emit candidate pairs, and run the three filters.

    Returns a deterministic list sorted by ``(a.chunk_id, b.chunk_id)``.
    The LLM judge consumes this list directly.
    """
    chunks = _iter_all_chunks(store)
    if not chunks:
        return []

    if embedder is None:
        embedder = BGEEmbedder()

    # Cache chunk vectors for the near-dup filter. We re-embed passages
    # rather than reading them back from LanceDB, which keeps this path
    # storage-agnostic and avoids LanceDB-specific column access for
    # the vector column.
    texts = [c.text for c in chunks]
    vecs = embedder.encode_passages(texts)
    vector_map: dict[str, np.ndarray] = {
        c.chunk_id: np.asarray(vecs[i], dtype=np.float32) for i, c in enumerate(chunks)
    }

    raw_pairs: list[CandidatePair] = []
    for c in chunks:
        # Use each chunk body as a query — hybrid mode reuses P2's
        # dense + BM25 RRF fusion, which is the retrieval primitive the
        # rest of the agent stack is built on.
        hits = query(c.text, store=store, embedder=embedder, mode="hybrid", k=top_k)
        for h in hits:
            if h.chunk_id == c.chunk_id:
                continue
            b_ref = ChunkRef(
                chunk_id=h.chunk_id,
                source_rel=h.source_rel,
                heading_path=h.heading_path,
                text=h.text,
            )
            raw_pairs.append(_canonical(c, b_ref, retrieval_score=h.score))

    filtered = filter_pairs(raw_pairs, vectors=vector_map, dup_threshold=dup_threshold)
    filtered.sort(key=lambda p: (p.a.chunk_id, p.b.chunk_id))
    return filtered
