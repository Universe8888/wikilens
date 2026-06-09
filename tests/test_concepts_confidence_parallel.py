"""concepts + confidence parallelization: order-identity (M6 Phase 4f).

Both detect_unnamed_concepts and run_confidence sort their findings before
returning, so completion order can never leak into output — but we still prove
workers=1 and workers=8 yield byte-identical results with content-deterministic
judges, and that real concurrency happens (barrier test).
"""

from __future__ import annotations

import threading
from unittest.mock import patch

import numpy as np

from wikilens.clustering import ChunkPoint, Cluster
from wikilens.concepts import ConceptProposal, detect_unnamed_concepts
from wikilens.confidence import ConfidenceVerdict, run_confidence

# --------------------------------------------------------------------------- #
# concepts                                                                    #
# --------------------------------------------------------------------------- #


def _point(chunk_id: str, text: str) -> ChunkPoint:
    return ChunkPoint(
        chunk_id=chunk_id, source_rel=f"{chunk_id}.md", text=text,
        vector=np.zeros(2, dtype=np.float32),
    )


class _ContentConceptJudge:
    """Proposes a term derived from the cluster's first chunk_id (deterministic)."""

    name = "content-concept"

    def propose(self, points):  # type: ignore[no-untyped-def]
        first = points[0].chunk_id if points else "x"
        # Confidence varies by id so the descending sort has something to do.
        conf = 0.5 + (hash(first) % 50) / 100.0
        return ConceptProposal(
            proposed_term=f"unnamed-{first}", confidence=conf, rationale="r"
        )


def _concept_clusters(n: int) -> list[Cluster]:
    # Each cluster's text never contains its proposed term -> all pass absence.
    return [
        Cluster(cluster_id=i, points=(_point(f"c{i}a", "alpha"), _point(f"c{i}b", "beta")))
        for i in range(n)
    ]


class TestConceptsParallel:
    def test_serial_and_parallel_identical(self, tmp_path):
        clusters = _concept_clusters(12)
        with patch("wikilens.concepts.LanceDBStore") as store, patch(
            "wikilens.concepts.cluster_chunks", return_value=clusters
        ):
            store.return_value.iter_rows.return_value = [
                {"chunk_id": "x", "source_rel": "x.md", "text": "t", "vector": [0.0, 0.0]}
            ]
            serial = detect_unnamed_concepts(
                str(tmp_path / "db"), "chunks", _ContentConceptJudge(),
                top_k=100, absence_threshold=0.99, workers=1,
            )
        with patch("wikilens.concepts.LanceDBStore") as store, patch(
            "wikilens.concepts.cluster_chunks", return_value=clusters
        ):
            store.return_value.iter_rows.return_value = [
                {"chunk_id": "x", "source_rel": "x.md", "text": "t", "vector": [0.0, 0.0]}
            ]
            parallel = detect_unnamed_concepts(
                str(tmp_path / "db"), "chunks", _ContentConceptJudge(),
                top_k=100, absence_threshold=0.99, workers=8,
            )
        sig_s = [(f.proposed_term, f.confidence) for f in serial]
        sig_p = [(f.proposed_term, f.confidence) for f in parallel]
        assert sig_s == sig_p
        assert len(serial) == 12


# --------------------------------------------------------------------------- #
# confidence                                                                  #
# --------------------------------------------------------------------------- #


class _ContentConfidenceJudge:
    """Level derives from the claim text (deterministic, order-independent)."""

    name = "content-conf"

    def classify(self, claim: str, note_context: str) -> ConfidenceVerdict:
        # Claims containing 'LOW' get a reportable low level; others high.
        level = 1 if "LOW" in claim else 5
        return ConfidenceVerdict(level=level, rationale=claim, confidence=0.9)


def _make_vault(tmp_path, n_claims: int):
    # One note, n sentences; half marked LOW so the threshold keeps some.
    lines = []
    for i in range(n_claims):
        marker = "LOW" if i % 2 == 0 else "HI"
        lines.append(f"This is claim {marker} number {i} with enough words here.")
    (tmp_path / "note.md").write_text("\n\n".join(lines), encoding="utf-8")
    return str(tmp_path)


class TestConfidenceParallel:
    def test_serial_and_parallel_identical(self, tmp_path):
        vault = _make_vault(tmp_path, 16)
        serial = run_confidence(vault, _ContentConfidenceJudge(), threshold=2, workers=1)
        parallel = run_confidence(vault, _ContentConfidenceJudge(), threshold=2, workers=8)
        sig_s = [(f.note_rel, f.level, f.claim_text) for f in serial.findings]
        sig_p = [(f.note_rel, f.level, f.claim_text) for f in parallel.findings]
        assert sig_s == sig_p
        assert serial.judge_calls == parallel.judge_calls == 16
        assert len(serial.findings) > 0  # the LOW claims were kept

    def test_confidence_actually_parallelizes(self, tmp_path):
        n = 6
        vault = _make_vault(tmp_path, n)
        barrier = threading.Barrier(n, timeout=5)

        class BarrierJudge:
            name = "barrier"

            def classify(self, claim, note_context):  # type: ignore[no-untyped-def]
                barrier.wait()
                return ConfidenceVerdict(level=1, rationale=claim, confidence=0.9)

        report = run_confidence(vault, BarrierJudge(), threshold=2, workers=n)
        assert report.judge_calls == n  # no deadlock => real concurrency
