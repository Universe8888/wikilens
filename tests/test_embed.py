"""Embedder tests — real model calls (BGE-small is local, ~130MB cached).

These tests use the actual BGE model to catch integration bugs (wrong
dim, missing normalization, prefix regressions). They run fast (~2s total)
once the model is cached.
"""

from __future__ import annotations

import numpy as np
import pytest

from wikilens.embed import BGE_QUERY_INSTRUCTION, DEFAULT_DIM, BGEEmbedder, Embedder


@pytest.fixture(scope="module")
def embedder() -> BGEEmbedder:
    e = BGEEmbedder()
    e._ensure_model()  # warm once for the whole module
    return e


def test_bge_implements_embedder_protocol(embedder: BGEEmbedder):
    assert isinstance(embedder, Embedder)


def test_encode_query_returns_correct_dim(embedder: BGEEmbedder):
    v = embedder.encode_query("what is photosynthesis")
    assert v.shape == (DEFAULT_DIM,)


def test_encode_passages_returns_batch(embedder: BGEEmbedder):
    vecs = embedder.encode_passages(["first passage", "second one", "third"])
    assert vecs.shape == (3, DEFAULT_DIM)


def test_encode_passages_empty_batch(embedder: BGEEmbedder):
    vecs = embedder.encode_passages([])
    assert vecs.shape == (0, DEFAULT_DIM)


def test_embeddings_are_l2_normalized(embedder: BGEEmbedder):
    v = embedder.encode_query("anything")
    norm = float(np.linalg.norm(v))
    assert abs(norm - 1.0) < 1e-4

    vecs = embedder.encode_passages(["a", "b", "c"])
    norms = np.linalg.norm(vecs, axis=1)
    assert np.allclose(norms, 1.0, atol=1e-4)


def test_query_prefix_actually_changes_output(embedder: BGEEmbedder):
    """encode_query must prepend the instruction — a silent regression
    (someone removing the prefix to 'simplify') would destroy retrieval.
    """
    model = embedder._model
    q = "photosynthesis explained"
    raw = model.encode(q, normalize_embeddings=True, convert_to_numpy=True)
    prefixed = model.encode(
        BGE_QUERY_INSTRUCTION + q, normalize_embeddings=True, convert_to_numpy=True
    )
    via_encode_query = embedder.encode_query(q)

    # encode_query result must match the prefixed path, not the raw path
    assert np.allclose(via_encode_query, prefixed, atol=1e-5)
    assert not np.allclose(via_encode_query, raw, atol=1e-3)


def test_passage_encoding_does_not_apply_prefix(embedder: BGEEmbedder):
    """Passages must be encoded raw — applying the query prefix at ingest
    is the classic BGE retrieval-breaker (pre-logged as G2).
    """
    model = embedder._model
    text = "plants turn light into sugar"
    raw = model.encode(text, normalize_embeddings=True, convert_to_numpy=True)
    via_passage = embedder.encode_passages([text])[0]
    assert np.allclose(via_passage, raw, atol=1e-5)


def test_query_and_matching_passage_have_high_similarity(embedder: BGEEmbedder):
    """End-to-end sanity: a query and a passage about the same topic
    should have meaningfully higher cosine similarity than unrelated text.
    """
    q = embedder.encode_query("how do plants make food")
    relevant = embedder.encode_passages(
        ["Photosynthesis is how plants convert sunlight into glucose."]
    )[0]
    irrelevant = embedder.encode_passages(
        ["The stock market closed lower on Thursday after Fed remarks."]
    )[0]

    sim_relevant = float(np.dot(q, relevant))  # equals cosine since L2-normalized
    sim_irrelevant = float(np.dot(q, irrelevant))

    assert sim_relevant > sim_irrelevant + 0.1  # real signal, not noise
