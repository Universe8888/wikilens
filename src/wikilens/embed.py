"""Embedding backend interface + BGE-small-en-v1.5 implementation.

Research-backed defaults (BGE model card + MTEB leaderboard 2024):

- Query-instruction prefix on queries ONLY. Never apply to passages at
  ingest — it destroys retrieval. This module enforces that split by
  exposing distinct `encode_query` and `encode_passage` methods.
- L2-normalized embeddings so downstream store can use cosine as
  dot-product (faster and equivalent).
"""

from __future__ import annotations

import logging
import warnings
from collections.abc import Sequence
from typing import Protocol, runtime_checkable

import numpy as np

_log = logging.getLogger(__name__)

# BGE-family query instruction — from the BAAI/bge-small-en-v1.5 model card.
# Applied to queries only; passages are encoded raw.
BGE_QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "

DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"
# Set to a concrete HF revision SHA (from the model card's "Files → main" dropdown)
# to lock weights against upstream being retagged or the account being compromised.
# Leaving this as None fetches whatever "main" is at first run — acceptable for
# dev, risky for reproducibility and supply chain. Callers can override via the
# `revision` kwarg.
DEFAULT_REVISION: str | None = None
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

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        batch_size: int = 32,
        revision: str | None = DEFAULT_REVISION,
    ):
        self._model_name = model_name
        self._batch_size = batch_size
        self._revision = revision
        self._model = None  # lazy
        self.dim = DEFAULT_DIM

    def _ensure_model(self):
        if self._model is None:
            # Heavy import kept inside method so unit tests that don't
            # embed don't pay the sentence-transformers import cost.
            from sentence_transformers import SentenceTransformer

            if self._revision is None:
                warnings.warn(
                    f"BGEEmbedder: no revision SHA pinned for {self._model_name!r}. "
                    "Fetching whatever 'main' is — set DEFAULT_REVISION to a commit SHA "
                    "for reproducibility and supply-chain safety.",
                    stacklevel=3,
                )
            kwargs: dict[str, str] = {}
            if self._revision is not None:
                kwargs["revision"] = self._revision
            self._model = SentenceTransformer(self._model_name, **kwargs)
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
