"""Vector store interface + LanceDB implementation.

Separates dense (vector) and sparse (BM25 / full-text) retrieval. Both
indices live on the same LanceDB table; fusion happens at the query
layer (step 8.5), not here.

Design decisions:

- Pluggable VectorStore protocol so the eval harness can A/B alternatives.
- Cosine metric on dense search (embeddings are already L2-normalized by
  BGEEmbedder, so cosine == dot product; cheap and rank-equivalent to L2
  on unit vectors, but with explicit semantics).
- Deterministic chunk_id is the primary key; upsert = delete+add, so
  re-ingestion replaces rows in place (supports P3 incremental indexing).
- FTS index uses LanceDB's tantivy integration, default English tokenizer.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import lancedb
import pyarrow as pa

from wikilens.ingest import Chunk

DEFAULT_TABLE = "chunks"

# chunk_id is a deterministic SHA-256 digest (see ingest.chunk_note) — 32 hex
# chars, but tests use shorter synthetic ids too. We only need to guarantee
# the string carries no SQL metacharacters so the delete f-string below can
# never become an injection sink if the ID scheme changes upstream.
_CHUNK_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SearchHit:
    """A single retrieval result with the fields needed for ranking + display."""

    chunk_id: str
    source_rel: str
    heading_path: tuple[str, ...]
    text: str
    score: float  # higher is better (cosine similarity for dense; BM25 for FTS)


@runtime_checkable
class VectorStore(Protocol):
    def upsert(self, chunks: Sequence[Chunk], vectors: Any) -> int:
        """Insert or replace chunks + their dense vectors. Returns row count added."""
        ...

    def count(self) -> int:
        """Total chunks in the store."""
        ...

    def search_dense(self, query_vector: Any, k: int) -> list[SearchHit]:
        """Dense cosine search, returning top-k hits."""
        ...

    def search_fts(self, query_text: str, k: int) -> list[SearchHit]:
        """BM25 full-text search, returning top-k hits."""
        ...


def _build_schema(dim: int) -> pa.Schema:
    return pa.schema(
        [
            pa.field("chunk_id", pa.string()),
            pa.field("source_rel", pa.string()),
            pa.field("heading_path", pa.string()),  # joined "A > B > C" for display
            pa.field("text", pa.string()),
            pa.field("token_count", pa.int32()),
            pa.field("chunk_index", pa.int32()),
            pa.field("content_hash", pa.string()),
            pa.field("vector", pa.list_(pa.float32(), dim)),
        ]
    )


class LanceDBStore:
    """LanceDB-backed store with dense + FTS indices on the same table."""

    def __init__(
        self,
        db_path: str | Path,
        dim: int,
        table_name: str = DEFAULT_TABLE,
    ):
        self._db_path = str(db_path)
        self._dim = dim
        self._table_name = table_name
        self._db = lancedb.connect(self._db_path)
        self._table: lancedb.table.Table | None = None
        self._fts_dirty = True  # FTS index needs (re)building after upserts

    def _get_or_create_table(self) -> lancedb.table.Table:
        if self._table is not None:
            return self._table
        # list_tables() returns a paginated object with .tables (a list); the
        # deprecated table_names() returned a plain list. Handle both shapes
        # defensively so a future lancedb upgrade that reverts the API still works.
        raw = self._db.list_tables()
        names = getattr(raw, "tables", raw)
        if self._table_name in names:
            self._table = self._db.open_table(self._table_name)
        else:
            self._table = self._db.create_table(
                self._table_name, schema=_build_schema(self._dim)
            )
        return self._table

    def _chunk_to_row(self, chunk: Chunk, vector: Any) -> dict[str, Any]:
        return {
            "chunk_id": chunk.chunk_id,
            "source_rel": chunk.source_rel,
            "heading_path": " > ".join(chunk.heading_path),
            "text": chunk.text,
            "token_count": int(chunk.token_count),
            "chunk_index": int(chunk.chunk_index),
            "content_hash": chunk.content_hash,
            "vector": list(vector),
        }

    def upsert(self, chunks: Sequence[Chunk], vectors: Any) -> int:
        if len(chunks) == 0:
            return 0
        if len(chunks) != len(vectors):
            raise ValueError(
                f"chunks/vectors length mismatch: {len(chunks)} vs {len(vectors)}"
            )
        table = self._get_or_create_table()

        # Delete any rows with the same chunk_ids first (upsert semantics).
        # Hard-validate the ID shape so the f-string below cannot become
        # an injection sink if the ID scheme ever changes upstream.
        ids = [c.chunk_id for c in chunks]
        for i in ids:
            if not _CHUNK_ID_RE.match(i):
                raise ValueError(f"invalid chunk_id shape: {i!r}")
        quoted = ",".join(f"'{i}'" for i in ids)
        try:
            table.delete(f"chunk_id IN ({quoted})")
        except (ValueError, RuntimeError, OSError) as e:
            # Some lancedb builds raise on a no-op delete; a fresh table has
            # no rows to delete, which is fine. Log anything stranger.
            _log.debug("pre-upsert delete skipped: %s", e)

        rows = [self._chunk_to_row(c, v) for c, v in zip(chunks, vectors, strict=True)]
        table.add(rows)
        self._fts_dirty = True
        return len(rows)

    def count(self) -> int:
        """Row count. Raises on corruption — callers decide how to interpret."""
        return self._get_or_create_table().count_rows()

    def ensure_fts_index(self) -> None:
        """Build (or rebuild) the FTS index. Idempotent; cheap if already built."""
        if not self._fts_dirty:
            return
        table = self._get_or_create_table()
        if table.count_rows() == 0:
            return
        # `replace=True` makes this a full rebuild; for small vaults this is
        # fast. Incremental FTS updates land in P3.
        table.create_fts_index("text", replace=True)
        self._fts_dirty = False

    def _row_to_hit(self, row: dict, score_key: str, higher_is_better: bool) -> SearchHit:
        raw = row.get(score_key)
        score = float(raw) if raw is not None else 0.0
        # LanceDB dense returns _distance where lower is better. Convert to
        # a similarity-style score (higher = better) for uniform downstream use.
        if not higher_is_better:
            score = -score
        heading = row.get("heading_path") or ""
        hp = tuple(s for s in heading.split(" > ") if s) if heading else ()
        return SearchHit(
            chunk_id=row["chunk_id"],
            source_rel=row["source_rel"],
            heading_path=hp,
            text=row["text"],
            score=score,
        )

    def search_dense(self, query_vector: Any, k: int) -> list[SearchHit]:
        table = self._get_or_create_table()
        if table.count_rows() == 0:
            return []
        results = (
            table.search(list(query_vector), query_type="vector")
            .metric("cosine")
            .limit(k)
            .to_list()
        )
        # With cosine metric, _distance = 1 - cosine_similarity → lower is better.
        # Convert to similarity.
        out: list[SearchHit] = []
        for row in results:
            d = row.get("_distance")
            sim = 1.0 - float(d) if d is not None else 0.0
            heading = row.get("heading_path") or ""
            hp = tuple(s for s in heading.split(" > ") if s) if heading else ()
            out.append(
                SearchHit(
                    chunk_id=row["chunk_id"],
                    source_rel=row["source_rel"],
                    heading_path=hp,
                    text=row["text"],
                    score=sim,
                )
            )
        return out

    def search_fts(self, query_text: str, k: int) -> list[SearchHit]:
        table = self._get_or_create_table()
        if table.count_rows() == 0:
            return []
        self.ensure_fts_index()
        try:
            results = (
                table.search(query_text, query_type="fts").limit(k).to_list()
            )
        except (ValueError, RuntimeError) as e:
            # Empty-query / tokenizer edge cases are expected and recoverable.
            # A broken FTS index or IO error should NOT silently degrade to
            # dense-only — log loudly so hybrid/rerank callers can see it.
            _log.warning("FTS search failed on query %r: %s", query_text, e)
            return []
        # FTS _score is BM25; higher is better.
        return [self._row_to_hit(row, "_score", higher_is_better=True) for row in results]
