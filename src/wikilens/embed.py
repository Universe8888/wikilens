"""Embedding backend interface + BGE-small-en-v1.5 implementation.

Research-backed defaults (BGE model card + MTEB leaderboard 2024):

- Query-instruction prefix on queries ONLY. Never apply to passages at
  ingest — it destroys retrieval. This module enforces that split by
  exposing distinct `encode_query` and `encode_passage` methods.
- L2-normalized embeddings so downstream store can use cosine as
  dot-product (faster and equivalent).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

import numpy as np

# BGE-family query instruction — from the BAAI/bge-small-en-v1.5 model card.
# Applied to queries only; passages are encoded raw.
BGE_QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "

DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"
DEFAULT_DIM = 384


@runtime_checkable
class Embedder(Protocol):
    """Pluggable embedder interface.

    Two distinct encoding entry points — query vs passage — so callers
    cannot accidentally apply the query instruction to ingested passages.
    """

    dim: int

    def encode_query(self, text: str) -> np.ndarray:
        """Encode a single query string. Applies instruction prefix."""
        ...

    def encode_passages(self, texts: Sequence[str]) -> np.ndarray:
        """Encode a batch of passage strings. No instruction prefix.

        Returns array of shape (len(texts), dim).
        """
        ...


class BGEEmbedder:
    """Local BGE-small-en-v1.5 embedder via sentence-transformers.

    Lazy-loads the model on first use so `import wikilens.embed` is cheap
    for CLIs that don't actually embed.
    """

    def __init__(self, model_name: str = DEFAULT_MODEL, batch_size: int = 32):
        self._model_name = model_name
        self._batch_size = batch_size
        self._model = None  # lazy
        self.dim = DEFAULT_DIM

    def _ensure_model(self):
        if self._model is None:
            # Heavy import kept inside method so unit tests that don't
            # embed don't pay the sentence-transformers import cost.
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self._model_name)
            # Sanity-check the declared dim matches the loaded model.
            actual = self._model.get_sentence_embedding_dimension()
            if actual != self.dim:
                self.dim = actual
        return self._model

    def encode_query(self, text: str) -> np.ndarray:
        model = self._ensure_model()
        prefixed = BGE_QUERY_INSTRUCTION + text
        vec = model.encode(
            prefixed,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return vec

    def encode_passages(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        model = self._ensure_model()
        vecs = model.encode(
            list(texts),
            batch_size=self._batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return vecs
