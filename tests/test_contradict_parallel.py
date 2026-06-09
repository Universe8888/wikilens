"""judge_pairs() parallelization: order- and result-identity (M6 Phase 4c).

The contradict judging loop is extracted into ``judge_pairs(pairs, judge, ...)``
so it can run over ``parallel_map``. The invariant under test: for a
content-deterministic judge (verdict depends only on the pair text, never on
call order), the findings produced with ``workers=8`` are byte-identical to
``workers=1`` — same set, same order. A seeded MockJudge can't prove this
(its verdicts cycle by call index), so we use a content-keyed fake.
"""

from __future__ import annotations

import threading

from wikilens.contradict import ChunkRef, _canonical
from wikilens.contradict_format import Finding, judge_pairs
from wikilens.judge import JudgeVerdict


class ContentJudge:
    """Deterministic judge: a pair contradicts iff text_a contains 'X'.

    Verdict depends ONLY on content, so the outcome is independent of the
    order in which pairs are judged — the property that lets us compare
    serial vs parallel output. Also records max observed concurrency.
    """

    name = "content"

    def __init__(self) -> None:
        self.calls = 0
        self._live = 0
        self.max_concurrent = 0
        self._lock = threading.Lock()

    def score_pair(self, text_a: str, text_b: str) -> JudgeVerdict:
        with self._lock:
            self.calls += 1
            self._live += 1
            self.max_concurrent = max(self.max_concurrent, self._live)
        try:
            if "X" in text_a:
                return JudgeVerdict(
                    verdict=True, type="factual", score=0.9, reasoning=text_a
                )
            return JudgeVerdict(verdict=False, type="none", score=0.0, reasoning="no")
        finally:
            with self._lock:
                self._live -= 1


def _pair(i: int, marker: str) -> object:
    a = ChunkRef(chunk_id=f"a{i}", source_rel="a.md", heading_path="", text=f"{marker}{i}")
    b = ChunkRef(chunk_id=f"b{i}", source_rel="b.md", heading_path="", text=f"plain{i}")
    return _canonical(a, b, retrieval_score=0.5)


class TestJudgePairsParallel:
    def test_serial_and_parallel_findings_identical(self) -> None:
        # 20 pairs; even indices carry 'X' (contradiction), odd don't.
        pairs = [_pair(i, "X" if i % 2 == 0 else "plain") for i in range(20)]

        serial = judge_pairs(pairs, ContentJudge(), min_score=0.5, workers=1)
        parallel = judge_pairs(pairs, ContentJudge(), min_score=0.5, workers=8)

        # Same findings, same ORDER (input order), regardless of worker count.
        def sig(fs: list[Finding]) -> list[str]:
            return [f.pair.a.chunk_id for f in fs]

        assert sig(serial) == sig(parallel)
        # 10 even-index pairs cleared the gate.
        assert len(serial) == 10
        assert all(f.verdict.verdict for f in serial)

    def test_min_score_gate_applied(self) -> None:
        pairs = [_pair(i, "X") for i in range(5)]
        # All would be 0.9; a 0.95 gate drops them all.
        findings = judge_pairs(pairs, ContentJudge(), min_score=0.95, workers=4)
        assert findings == []

    def test_findings_follow_input_order_not_completion(self) -> None:
        pairs = [_pair(i, "X") for i in range(12)]
        findings = judge_pairs(pairs, ContentJudge(), min_score=0.5, workers=8)
        # chunk_ids must be a0, a1, ... a11 in order despite parallel judging.
        assert [f.pair.a.chunk_id for f in findings] == [f"a{i}" for i in range(12)]

    def test_actually_parallelizes(self) -> None:
        # A barrier judge proves real concurrency deterministically: all N
        # score_pair calls must arrive at the barrier before any returns, so
        # if judge_pairs were secretly serial this would deadlock (5s timeout).
        n = 8
        barrier = threading.Barrier(n, timeout=5)

        class BarrierJudge:
            name = "barrier"

            def score_pair(self, text_a: str, text_b: str) -> JudgeVerdict:
                barrier.wait()
                return JudgeVerdict(
                    verdict=True, type="factual", score=0.9, reasoning=text_a
                )

        pairs = [_pair(i, "X") for i in range(n)]
        findings = judge_pairs(pairs, BarrierJudge(), min_score=0.5, workers=n)
        # Reaching here (no deadlock) proves all n ran concurrently; order held.
        assert [f.pair.a.chunk_id for f in findings] == [f"a{i}" for i in range(n)]

    def test_empty_pairs(self) -> None:
        assert judge_pairs([], ContentJudge(), min_score=0.5, workers=8) == []
