"""Cross-encoder reranker (BGE-reranker-base).

Takes (query, passage) pairs and returns a single relevance score per pair.
Used to re-rank the top-K candidates from hybrid retrieval before returning
the final top-k to the user.

Research: BGE-reranker-base is English-only, 140MB, and typically adds
5-10 points of recall@5 when applied to dense or hybrid top-20. Well
within the 2s p95 budget on a CPU for K=20 passages.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

DEFAULT_RERANKER_MODEL = "BAAI/bge-reranker-base"
# See embed.py — pin a concrete HF revision SHA for supply-chain safety.
DEFAULT_RERANKER_REVISION: str | None = None


@runtime_checkable
class Reranker(Protocol):
    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        """Return one relevance score per passage (higher = more relevant)."""
        ...


class BGEReranker:
    """Cross-encoder reranker. Lazy-loaded so import is cheap."""

    def __init__(
        self,
        model_name: str = DEFAULT_RERANKER_MODEL,
        revision: str | None = DEFAULT_RERANKER_REVISION,
    ):
        self._model_name = model_name
        self._revision = revision
        self._model = None

    def _ensure_model(self):
        if self._model is None:
            from sentence_transformers import CrossEncoder

            kwargs: dict[str, str] = {}
            if self._revision is not None:
                kwargs["revision"] = self._revision
            self._model = CrossEncoder(self._model_name, **kwargs)
        return self._model

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        if not passages:
            return []
        model = self._ensure_model()
        pairs = [(query, p) for p in passages]
        scores = model.predict(pairs, show_progress_bar=False)
        return [float(s) for s in scores]
