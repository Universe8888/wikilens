"""judge_drift_pairs() parallelization (M6 Phase 4e).

The drift judging loop is extracted into ``judge_drift_pairs(pairs, judge, ...)``
so it runs over ``parallel_map``. Invariant: a content-deterministic judge
yields byte-identical findings (same members, same order) and the same
``pairs_judged`` count at workers=1 vs workers=8. The findings keep input order
(drift appends in pairs_to_judge order today), so JSON output is unchanged.
"""

from __future__ import annotations

import threading

from wikilens.drift import CandidatePair, Revision
from wikilens.drift_format import judge_drift_pairs
from wikilens.drift_judge import DriftVerdict


def _pair(i: int, drift_marker: bool) -> CandidatePair:
    rev_b = Revision(sha=f"b{i}", timestamp=1000 + i, rel_path=f"n{i}.md", content="x")
    rev_a = Revision(sha=f"a{i}", timestamp=2000 + i, rel_path=f"n{i}.md", content="y")
    return CandidatePair(
        note_rel=f"n{i}.md",
        before=rev_b,
        after=rev_a,
        before_claim=("DRIFT" if drift_marker else "same") + f"-before-{i}",
        after_claim=f"after-{i}",
        cosine=0.7,
    )


class ContentDriftJudge:
    """Drift iff the before_claim contains 'DRIFT'. Order-independent."""

    name = "content-drift"

    def __init__(self) -> None:
        self.calls = 0
        self._lock = threading.Lock()

    def score_pair(
        self,
        note_rel: str,
        before_claim: str,
        before_date: str,
        after_claim: str,
        after_date: str,
    ) -> DriftVerdict:
        with self._lock:
            self.calls += 1
        if "DRIFT" in before_claim:
            return DriftVerdict(drift=True, type="reversal", score=5, reasoning=before_claim)
        return DriftVerdict(drift=False, type="none", score=1, reasoning="stable")


class TestJudgeDriftPairs:
    def test_serial_and_parallel_identical(self) -> None:
        pairs = [_pair(i, drift_marker=(i % 3 == 0)) for i in range(15)]
        f_serial, judged_serial = judge_drift_pairs(
            pairs, ContentDriftJudge(), min_score=2, workers=1
        )
        f_par, judged_par = judge_drift_pairs(
            pairs, ContentDriftJudge(), min_score=2, workers=8
        )
        sig_s = [(e.note_rel, e.score, e.reasoning) for e in f_serial]
        sig_p = [(e.note_rel, e.score, e.reasoning) for e in f_par]
        assert sig_s == sig_p
        assert judged_serial == judged_par == 15
        # i % 3 == 0 -> 5 drifts (i=0,3,6,9,12).
        assert len(f_serial) == 5

    def test_findings_follow_input_order(self) -> None:
        pairs = [_pair(i, drift_marker=True) for i in range(10)]
        findings, _ = judge_drift_pairs(pairs, ContentDriftJudge(), min_score=2, workers=8)
        assert [e.note_rel for e in findings] == [f"n{i}.md" for i in range(10)]

    def test_min_score_gate(self) -> None:
        # All score=5; a min_score of 6 (above max) drops everything.
        pairs = [_pair(i, drift_marker=True) for i in range(4)]
        findings, judged = judge_drift_pairs(pairs, ContentDriftJudge(), min_score=6, workers=4)
        assert findings == []
        assert judged == 4  # all were still judged

    def test_empty(self) -> None:
        findings, judged = judge_drift_pairs([], ContentDriftJudge(), min_score=2, workers=8)
        assert findings == []
        assert judged == 0

    def test_actually_parallelizes(self) -> None:
        n = 6
        barrier = threading.Barrier(n, timeout=5)

        class BarrierJudge:
            name = "barrier"

            def score_pair(self, note_rel, before_claim, before_date, after_claim, after_date):  # type: ignore[no-untyped-def]
                barrier.wait()
                return DriftVerdict(drift=True, type="reversal", score=5, reasoning="x")

        pairs = [_pair(i, drift_marker=True) for i in range(n)]
        findings, _ = judge_drift_pairs(pairs, BarrierJudge(), min_score=2, workers=n)
        assert len(findings) == n  # no deadlock => real concurrency
