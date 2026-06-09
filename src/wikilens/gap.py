"""Gap Generator — clustering + per-cluster gap proposal pipeline (P5).

Walks every chunk in an ingested vault, k-means clusters their
embeddings, then invokes a ``Generator`` per cluster to propose
unanswered questions implied by the cluster's content.

This module owns no LLM and no network — the cognitive kernel lives in
``generator.py``. Clustering happens here so the generator can stay
stateless and model-agnostic.
"""

from __future__ import annotations

import numpy as np

from wikilens.clustering import ChunkPoint, Cluster, cluster_chunks, default_k
from wikilens.generator import GapFinding, Generator
from wikilens.store import VectorStore

_default_k = default_k  # re-exported for test compat

DEFAULT_TOP_GAPS_PER_CLUSTER = 3
DEFAULT_MIN_CLUSTER_SIZE = 3
DEFAULT_MAX_CLUSTERS = 30
DEFAULT_SEED = 42


def _iter_all_points(store: VectorStore) -> list[ChunkPoint]:
    """Pull every chunk + vector from the store via the Protocol."""
    rows = store.iter_rows(["chunk_id", "source_rel", "text", "vector"])
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
    workers: int = 1,
) -> tuple[list[Cluster], list[GapFinding]]:
    """End-to-end pipeline: full-table scan → cluster → per-cluster generate.

    ``workers`` (M6) sets the number of concurrent ``propose_gaps`` calls; the
    per-cluster results are collected in cluster order then flattened, so the
    findings list is identical for any worker count (``workers=1`` is serial).
    """
    from wikilens.executor import parallel_map

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

    to_process: list[Cluster] = list(clusters)
    if sample is not None and sample >= 0:
        to_process = to_process[:sample]

    # Parallelize the LLM call per cluster; parallel_map preserves cluster
    # order so the flattened findings are deterministic regardless of workers.
    per_cluster_candidates = parallel_map(
        lambda cluster: generator.propose_gaps(
            _cluster_chunks_as_input(cluster),
            top_k=top_gaps_per_cluster,
        ),
        to_process,
        max_workers=workers,
    )

    findings: list[GapFinding] = []
    for cluster, candidates in zip(to_process, per_cluster_candidates, strict=True):
        for candidate in candidates:
            findings.append(
                GapFinding(
                    cluster_id=cluster.cluster_id,
                    cluster_size=cluster.size,
                    candidate=candidate,
                )
            )
    return clusters, findings
