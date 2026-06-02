"""Shared clustering utilities for agents that cluster vault chunks."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

DEFAULT_MIN_CLUSTER_SIZE = 3
DEFAULT_MAX_CLUSTERS = 30
DEFAULT_SEED = 42


@dataclass(frozen=True)
class ChunkPoint:
    """Minimal per-chunk record needed for clustering + generator input."""

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


def default_k(n_chunks: int) -> int:
    """Default cluster count = round(sqrt(n_chunks)), clamped to sensible bounds."""
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
    """K-means cluster the given points, drop small clusters, cap total."""
    if not points:
        return []
    if len(points) < min_cluster_size:
        return []

    from sklearn.cluster import KMeans

    if k is None:
        k = default_k(len(points))
    k = min(k, len(points))

    matrix = np.stack([p.vector for p in points])
    model = KMeans(n_clusters=k, random_state=seed, n_init=10)
    labels = model.fit_predict(matrix)

    buckets: dict[int, list[ChunkPoint]] = {}
    for label, point in zip(labels, points, strict=True):
        buckets.setdefault(int(label), []).append(point)

    clusters: list[Cluster] = []
    for cluster_id, members in buckets.items():
        if len(members) < min_cluster_size:
            continue
        members.sort(key=lambda p: p.chunk_id)
        clusters.append(Cluster(cluster_id=cluster_id, points=tuple(members)))

    clusters.sort(key=lambda c: (-c.size, c.cluster_id))
    if max_clusters > 0:
        clusters = clusters[:max_clusters]
    return clusters
