"""Pluggable LLM judge interface for contradiction scoring (P4).

Separates the "cognitive kernel" (the reasoning LLM) from the control flow
(pair generation, filtering, CLI). Every concrete judge exposes the same
``score_pair`` entry point and returns a ``JudgeVerdict`` with the same
shape — swapping ``MockJudge`` for ``ClaudeJudge`` or ``OllamaJudge`` never
forces changes upstream.

Phase 4.1 ships only the protocol + ``MockJudge``. The real LLM-backed
judges land in Phase 4.2 (``ClaudeJudge``) and optionally 4.2+ (``OllamaJudge``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

ContradictionType = Literal["factual", "temporal", "none"]
ALL_TYPES: tuple[ContradictionType, ...] = ("factual", "temporal", "none")


@dataclass(frozen=True)
class JudgeVerdict:
    """Structured output of one pairwise judge call.

    Attributes:
        verdict: ``True`` iff the judge considers the two chunks a genuine
            contradiction of type ``factual`` or ``temporal``. ``False``
            for ``none`` (unrelated, reconcilable, or same claim). The
            CLI filters on ``verdict AND score >= --min-score``.
        type: which class of contradiction (P4 D4 scope). ``none`` iff
            ``verdict`` is False.
        score: judge's confidence in ``[0.0, 1.0]``. 0.0 for clean "no"
            verdicts, 1.0 for definitive contradictions.
        reasoning: short human-readable rationale. Surfaced in markdown
            output; also useful when hand-auditing false positives.
    """

    verdict: bool
    type: ContradictionType
    score: float
    reasoning: str

    def __post_init__(self) -> None:
        if not 0.0 <= self.score <= 1.0:
            raise ValueError(f"score must be in [0.0, 1.0], got {self.score!r}")
        if self.type not in ALL_TYPES:
            raise ValueError(f"type must be one of {ALL_TYPES}, got {self.type!r}")
        # Enforce the verdict/type coherence invariant: a True verdict
        # cannot carry type=none, and vice versa. Callers that violate
        # this crash early instead of silently emitting garbage.
        if self.verdict and self.type == "none":
            raise ValueError("verdict=True requires type in {factual, temporal}")
        if not self.verdict and self.type != "none":
            raise ValueError("verdict=False requires type='none'")


@runtime_checkable
class Judge(Protocol):
    """Protocol every judge backend implements.

    ``score_pair`` takes two chunk bodies (already retrieved, already
    filtered) and returns a single verdict. Implementations own their
    own prompt, model, and transport — the caller sees only
    ``JudgeVerdict``.
    """

    name: str

    def score_pair(self, text_a: str, text_b: str) -> JudgeVerdict:
        """Judge whether ``text_a`` and ``text_b`` contradict."""
        ...


class MockJudge:
    """Deterministic stand-in used by ``--judge none`` and unit tests.

    Returns verdicts from a pre-seeded sequence, cycling if exhausted. If
    no sequence is provided, returns a fixed "no contradiction" verdict
    so the plumbing path (pair gen → judge → format) can be exercised
    end-to-end without any model loading or API calls.
    """

    name = "mock"

    def __init__(self, verdicts: list[JudgeVerdict] | None = None):
        self._verdicts: list[JudgeVerdict] = list(verdicts) if verdicts else []
        self._idx = 0
        self.calls: int = 0

    def score_pair(self, text_a: str, text_b: str) -> JudgeVerdict:
        self.calls += 1
        if not self._verdicts:
            return JudgeVerdict(
                verdict=False,
                type="none",
                score=0.0,
                reasoning="mock judge: no seeded verdict",
            )
        v = self._verdicts[self._idx % len(self._verdicts)]
        self._idx += 1
        return v
