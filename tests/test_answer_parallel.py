"""draft_answers parallelization: input-order identity (M6 Phase 4g).

answer.draft_answers parallelizes ONLY the drafter.draft_stub LLM calls;
retrieval (embedding + LanceDB) stays serial on the main thread by design.
Invariant: the drafts list is byte-identical (same bodies, same order) at
workers=1 vs workers=8 for a content-deterministic drafter, and drafts always
follow input gap order.
"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock

import numpy as np

from wikilens.answer import GapInput, draft_answers


def _gap(i: int) -> GapInput:
    return GapInput(
        cluster_id=i,
        cluster_size=3,
        gap_question=f"Question number {i}?",
        suggested_note_title=f"note-{i}",
        rationale="r",
        supporting_chunk_ids=("c1",),
    )


def _mock_store() -> MagicMock:
    from wikilens.store import SearchHit

    hit = SearchHit(
        chunk_id="c1", source_rel="src.md", heading_path=("H",),
        text="Supporting evidence text.", score=0.9,
    )
    store = MagicMock()
    store.search_dense.return_value = [hit]
    store.search_fts.return_value = [hit]
    store.iter_rows.return_value = []
    return store


def _mock_embedder() -> MagicMock:
    embedder = MagicMock()
    embedder.encode_query.return_value = np.zeros(384, dtype=np.float32)
    return embedder


_VALID_BODY = (
    "## What the vault says\n\nEvidence from [^1].\n\n"
    "## Evidence gaps\n\n- gap.\n\n"
    "## Proposed answer\n\nAnswer body.\n\n"
    "## Related notes\n\n- none\n\n"
    "[^1]: c1\n"
)


class _ContentDrafter:
    """Body derives from the gap question (deterministic, order-independent)."""

    name = "content-drafter"

    def __init__(self) -> None:
        self.calls = 0
        self._lock = threading.Lock()

    def draft_stub(self, draft_input) -> str:  # type: ignore[no-untyped-def]
        with self._lock:
            self.calls += 1
        # Embed the gap question so identical inputs map to identical bodies.
        return _VALID_BODY.replace("Answer body.", f"Answer for {draft_input.gap_question}")


class TestDraftAnswersParallel:
    def test_serial_and_parallel_identical(self) -> None:
        gaps = [_gap(i) for i in range(12)]
        serial = draft_answers(
            gaps, _mock_store(), _mock_embedder(), _ContentDrafter(),
            top_k=5, mode="hybrid", min_supporting=1, workers=1,
        )
        parallel = draft_answers(
            gaps, _mock_store(), _mock_embedder(), _ContentDrafter(),
            top_k=5, mode="hybrid", min_supporting=1, workers=8,
        )
        sig_s = [(d.gap.suggested_note_title, d.body_markdown) for d in serial]
        sig_p = [(d.gap.suggested_note_title, d.body_markdown) for d in parallel]
        assert sig_s == sig_p
        assert len(serial) == 12

    def test_drafts_follow_input_gap_order(self) -> None:
        gaps = [_gap(i) for i in range(10)]
        drafts = draft_answers(
            gaps, _mock_store(), _mock_embedder(), _ContentDrafter(),
            top_k=5, mode="hybrid", min_supporting=1, workers=8,
        )
        assert [d.gap.suggested_note_title for d in drafts] == [
            f"note-{i}" for i in range(10)
        ]

    def test_actually_parallelizes(self) -> None:
        n = 5
        barrier = threading.Barrier(n, timeout=5)

        class BarrierDrafter:
            name = "barrier"

            def draft_stub(self, draft_input) -> str:  # type: ignore[no-untyped-def]
                barrier.wait()
                return _VALID_BODY

        gaps = [_gap(i) for i in range(n)]
        drafts = draft_answers(
            gaps, _mock_store(), _mock_embedder(), BarrierDrafter(),
            top_k=5, mode="hybrid", min_supporting=1, workers=n,
        )
        assert len(drafts) == n  # no deadlock => real concurrency
