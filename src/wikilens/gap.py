"""Gap Generator — clustering + per-cluster gap proposal pipeline (P5).

Walks every chunk in an ingested vault, k-means clusters their
embeddings, then invokes a ``Generator`` per cluster to propose
unanswered questions implied by the cluster's content.

Complexity:

- Full-table scan is O(n) via ``to_arrow().to_pylist()`` (G5 pattern).
- K-means is O(n · k · iterations) — effectively O(n) for fixed k.
- Generator is called at most ``max_clusters`` times regardless of vault
  size. This is the ``--max-clusters`` budget cap (D6).

This module owns no LLM and no network — the cognitive kernel lives in
``generator.py``. Clustering happens here so the generator can stay
stateless and model-agnostic.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np

from wikilens.generator import GapFinding, Generator
from wikilens.store import VectorStore

DEFAULT_TOP_GAPS_PER_CLUSTER = 3
DEFAULT_MIN_CLUSTER_SIZE = 3
DEFAULT_MAX_CLUSTERS = 30
DEFAULT_SEED = 42


@dataclass(frozen=True)
class ChunkPoint:
    """Minimal per-chunk record needed for clustering + generator input.

    ``vector`` is kept as a ``np.ndarray`` so the clustering matrix can
    be built cheaply with ``np.stack``. It's stripped before the record
    is passed to the generator — the model never sees raw embeddings.
    """

    chunk_id: str
    source_rel: str
    text: str
    vector: np.ndarray


@dataclass(frozen=True)
class Cluster:
    """One post-clustering bucket.

    ``points`` are already size-filtered (>= ``min_cluster_size``) by
    the time a ``Cluster`` exists. ``cluster_id`` is stable across
    runs for a given ``seed`` + chunk set.
    """

    cluster_id: int
    points: tuple[ChunkPoint, ...]

    @property
    def size(self) -> int:
        return len(self.points)


def _iter_all_points(store: VectorStore) -> list[ChunkPoint]:
    """Pull every chunk + vector from the store.

    LanceDB-specific: reuses the G5 pattern (``to_arrow().to_pylist()``)
    because ``LanceTable.to_list()`` doesn't exist. Vectors are returned
    as lists by Arrow; we re-wrap them in ``np.ndarray`` for clustering.
    """
    table = store._get_or_create_table()  # type: ignore[attr-defined]
    rows = table.to_arrow().to_pylist()
    out: list[ChunkPoint] = []
    for row in rows:
        vec = row.get("vector")
        if vec is None:
            continue
        out.append(
            ChunkPoint(
                chunk_id=row["chunk_id"],
                source_rel=row["source_rel"],
                text=row["text"],
                vector=np.asarray(vec, dtype=np.float32),
            )
        )
    return out


def _default_k(n_chunks: int) -> int:
    """Default cluster count = round(sqrt(n_chunks)), clamped to sensible bounds.

    At n=16 → k=4; n=100 → k=10; n=5000 → k=71. Floor is 2 (single-cluster
    gap-finding is degenerate); ceiling is unbounded here because
    ``max_clusters`` caps downstream anyway.
    """
    if n_chunks < 4:
        return max(1, n_chunks)
    return max(2, round(math.sqrt(n_chunks)))


def cluster_chunks(
    points: list[ChunkPoint],
    *,
    k: int | None = None,
    seed: int = DEFAULT_SEED,
    min_cluster_size: int = DEFAULT_MIN_CLUSTER_SIZE,
    max_clusters: int = DEFAULT_MAX_CLUSTERS,
) -> list[Cluster]:
    """K-means cluster the given points, drop small clusters, cap total.

    Returns clusters sorted by size descending (largest first), then by
    cluster_id ascending for deterministic tie-breaks.

    Edge cases:
    - Empty input → empty output.
    - Fewer points than ``min_cluster_size`` → empty output (every
      candidate cluster would be dropped).
    - Fewer distinct points than ``k`` → scikit-learn's KMeans falls
      back to fewer effective clusters; we still respect min_cluster_size.
    """
    if not points:
        return []
    if len(points) < min_cluster_size:
        return []

    # Local import so unit tests that don't touch clustering don't pay the
    # sklearn import cost. The wikilens gap CLI always pays it.
    from sklearn.cluster import KMeans

    if k is None:
        k = _default_k(len(points))
    # Can't request more clusters than we have points.
    k = min(k, len(points))

    matrix = np.stack([p.vector for p in points])
    model = KMeans(n_clusters=k, random_state=seed, n_init=10)
    labels = model.fit_predict(matrix)

    # Group points by cluster label.
    buckets: dict[int, list[ChunkPoint]] = {}
    for label, point in zip(labels, points, strict=True):
        buckets.setdefault(int(label), []).append(point)

    clusters: list[Cluster] = []
    for cluster_id, members in buckets.items():
        if len(members) < min_cluster_size:
            continue
        # Stable within-cluster ordering by chunk_id so tests are deterministic.
        members.sort(key=lambda p: p.chunk_id)
        clusters.append(Cluster(cluster_id=cluster_id, points=tuple(members)))

    # Sort: largest first, then cluster_id asc for ties.
    clusters.sort(key=lambda c: (-c.size, c.cluster_id))
    if max_clusters > 0:
        clusters = clusters[:max_clusters]
    return clusters


def _cluster_chunks_as_input(cluster: Cluster) -> list[tuple[str, str]]:
    return [(p.chunk_id, p.text) for p in cluster.points]


def generate_gaps(
    store: VectorStore,
    generator: Generator,
    *,
    k: int | None = None,
    seed: int = DEFAULT_SEED,
    min_cluster_size: int = DEFAULT_MIN_CLUSTER_SIZE,
    max_clusters: int = DEFAULT_MAX_CLUSTERS,
    top_gaps_per_cluster: int = DEFAULT_TOP_GAPS_PER_CLUSTER,
    sample: int | None = None,
) -> tuple[list[Cluster], list[GapFinding]]:
    """End-to-end pipeline: full-table scan → cluster → per-cluster generate.

    Returns both the surviving clusters and the flat list of findings.
    The clusters are returned alongside the findings so the CLI/formatter
    can report cluster statistics (size, chunk count) without re-walking
    the store.

    ``sample`` caps the number of generator calls (mirrors P4's
    ``--sample``). Applied AFTER clustering + sort, so sampling always
    hits the largest clusters first.
    """
    points = _iter_all_points(store)
    clusters = cluster_chunks(
        points,
        k=k,
        seed=seed,
        min_cluster_size=min_cluster_size,
        max_clusters=max_clusters,
    )
    if not clusters:
        return clusters, []

    to_process: Iterable[Cluster] = clusters
    if sample is not None and sample >= 0:
        to_process = list(clusters)[:sample]

    findings: list[GapFinding] = []
    for cluster in to_process:
        candidates = generator.propose_gaps(
            _cluster_chunks_as_input(cluster),
            top_k=top_gaps_per_cluster,
        )
        for candidate in candidates:
            findings.append(
                GapFinding(
                    cluster_id=cluster.cluster_id,
                    cluster_size=cluster.size,
                    candidate=candidate,
                )
            )
    return clusters, findings
