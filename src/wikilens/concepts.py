"""Unnamed Concept Detector — clustering + per-cluster concept proposal (P9).

Walks every chunk in an ingested vault, clusters their embeddings with
``gap.cluster_chunks``, then invokes a ``ConceptJudge`` per cluster to
propose the unnamed concept the cluster is circling around.

A finding is only kept when the proposed term is *absent* from most of
the cluster's chunks — a high ``term_freq_in_cluster`` means the concept
is already named in the notes, so it is not an "unnamed" concept.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from wikilens.embed import DEFAULT_DIM
from wikilens.gap import ChunkPoint, _iter_all_points, cluster_chunks
from wikilens.store import LanceDBStore

if TYPE_CHECKING:
    from wikilens.concept_judge import ConceptJudge


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConceptProposal:
    """Raw output from one judge call — a single proposed canonical term."""

    proposed_term: str
    confidence: float
    rationale: str


@dataclass(frozen=True)
class ConceptFinding:
    """One detected unnamed concept surviving the absence filter.

    Attributes:
        cluster_id: stable cluster label from k-means.
        proposed_term: canonical term the judge proposes.
        confidence: judge confidence, 0.0–1.0.
        rationale: one-sentence explanation from the judge.
        supporting_notes: distinct source_rel values in the cluster.
        evidence_chunks: chunk_ids in the cluster.
        term_freq_in_cluster: fraction of chunks whose text contains
            ``proposed_term`` (case-insensitive). Values near 0 mean the
            concept is genuinely unnamed in the vault.
    """

    cluster_id: int
    proposed_term: str
    confidence: float
    rationale: str
    supporting_notes: list[str]
    evidence_chunks: list[str]
    term_freq_in_cluster: float


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


def detect_unnamed_concepts(
    db_path: str,
    table_name: str,
    judge: ConceptJudge,
    *,
    max_clusters: int = 20,
    min_cluster_size: int = 3,
    top_k: int = 10,
    absence_threshold: float = 0.20,
) -> list[ConceptFinding]:
    """Full pipeline: scan → cluster → judge → filter → rank.

    Args:
        db_path: filesystem path to the LanceDB directory.
        table_name: name of the chunks table inside that database.
        judge: any ``ConceptJudge``-protocol object.
        max_clusters: cap on how many clusters the judge is called for.
        min_cluster_size: clusters smaller than this are discarded before
            the judge is ever called.
        top_k: maximum findings to return, sorted by confidence descending.
        absence_threshold: keep a finding only when ``term_freq_in_cluster``
            is strictly below this value — the concept must be mostly unnamed.

    Returns:
        ``ConceptFinding`` list sorted by confidence descending, len <= top_k.
    """
    store = LanceDBStore(db_path=db_path, dim=DEFAULT_DIM, table_name=table_name)
    points: list[ChunkPoint] = _iter_all_points(store)

    clusters = cluster_chunks(
        points,
        max_clusters=max_clusters,
        min_cluster_size=min_cluster_size,
    )

    findings: list[ConceptFinding] = []
    for cluster in clusters:
        cluster_pts = list(cluster.points)
        proposal: ConceptProposal = judge.propose(cluster_pts)

        term_lower = proposal.proposed_term.lower()
        hits = sum(1 for p in cluster_pts if term_lower in p.text.lower())
        freq = hits / len(cluster_pts) if cluster_pts else 0.0

        if freq >= absence_threshold:
            continue

        findings.append(
            ConceptFinding(
                cluster_id=cluster.cluster_id,
                proposed_term=proposal.proposed_term,
                confidence=proposal.confidence,
                rationale=proposal.rationale,
                supporting_notes=sorted({p.source_rel for p in cluster_pts}),
                evidence_chunks=[p.chunk_id for p in cluster_pts],
                term_freq_in_cluster=freq,
            )
        )

    findings.sort(key=lambda f: f.confidence, reverse=True)
    return findings[:top_k]
