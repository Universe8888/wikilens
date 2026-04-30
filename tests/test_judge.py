"""Tests for the Judge protocol + MockJudge (P4, Phase 4.1).

No LLM calls. Verifies the JudgeVerdict invariant and the MockJudge's
deterministic-cycle behavior so the rest of the pipeline can rely on it
as a stand-in during plumbing work.
"""

from __future__ import annotations

import pytest

from wikilens.judge import ALL_TYPES, Judge, JudgeVerdict, MockJudge


def test_judge_verdict_accepts_valid_shapes():
    v = JudgeVerdict(
        verdict=True, type="factual", score=0.9, reasoning="Paris vs Berlin"
    )
    assert v.verdict is True
    assert v.type == "factual"
    assert v.score == 0.9


def test_judge_verdict_rejects_score_out_of_range():
    with pytest.raises(ValueError, match="score must be in"):
        JudgeVerdict(verdict=False, type="none", score=1.5, reasoning="x")
    with pytest.raises(ValueError, match="score must be in"):
        JudgeVerdict(verdict=False, type="none", score=-0.1, reasoning="x")


def test_judge_verdict_rejects_unknown_type():
    with pytest.raises(ValueError, match="type must be one of"):
        JudgeVerdict(verdict=True, type="values", score=0.5, reasoning="x")  # type: ignore[arg-type]


def test_judge_verdict_enforces_verdict_type_coherence():
    # verdict=True requires type != "none"
    with pytest.raises(ValueError, match="verdict=True"):
        JudgeVerdict(verdict=True, type="none", score=0.9, reasoning="x")
    # verdict=False requires type == "none"
    with pytest.raises(ValueError, match="verdict=False"):
        JudgeVerdict(verdict=False, type="factual", score=0.1, reasoning="x")


def test_all_types_constant_matches_literal():
    assert ALL_TYPES == ("factual", "temporal", "none")


def test_mock_judge_default_returns_no_contradiction():
    j = MockJudge()
    v = j.score_pair("A says X", "B says Y")
    assert v.verdict is False
    assert v.type == "none"
    assert v.score == 0.0
    assert j.calls == 1


def test_mock_judge_cycles_through_seeded_verdicts():
    seeded = [
        JudgeVerdict(verdict=True, type="factual", score=0.9, reasoning="1"),
        JudgeVerdict(verdict=False, type="none", score=0.0, reasoning="2"),
        JudgeVerdict(verdict=True, type="temporal", score=0.7, reasoning="3"),
    ]
    j = MockJudge(verdicts=seeded)
    out = [j.score_pair("a", "b") for _ in range(7)]
    # Cycled: 1, 2, 3, 1, 2, 3, 1
    assert [v.reasoning for v in out] == ["1", "2", "3", "1", "2", "3", "1"]
    assert j.calls == 7


def test_mock_judge_conforms_to_judge_protocol():
    j = MockJudge()
    assert isinstance(j, Judge)
    assert j.name == "mock"
