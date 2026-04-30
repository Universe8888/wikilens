"""Pluggable LLM judge interface for contradiction scoring (P4).

Separates the "cognitive kernel" (the reasoning LLM) from the control flow
(pair generation, filtering, CLI). Every concrete judge exposes the same
``score_pair`` entry point and returns a ``JudgeVerdict`` with the same
shape — swapping ``MockJudge`` for ``ClaudeJudge`` or ``OllamaJudge`` never
forces changes upstream.

Phase 4.1 ships ``MockJudge``. Phase 4.2 ships ``ClaudeJudge``.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
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


_JUDGE_SYSTEM_PROMPT = """\
You are a precise fact-checker that detects contradictions between two text
passages from a personal knowledge base. A contradiction means the two passages
make incompatible claims about the same entity, attribute, or event.

Contradiction types in scope:
- factual: Two passages assert incompatible facts about the same entity/attribute.
  Example A: "Paris is the capital of France."
  Example B: "Berlin is the capital of France."
- temporal: Two passages assert X at one time and ¬X at another time, and the
  discrepancy is real rather than intentional revision.
  Example A (2022): "We use PostgreSQL for the main database."
  Example B (2024): "We migrated everything to MySQL last quarter."

NOT a contradiction (return type "none"):
- Same claim phrased differently.
- One passage is more specific than the other (subset, not conflict).
- Value differences ("I prefer X" vs "I prefer Y").
- Definitional differences that are both valid in different frames.
- Passages about unrelated topics.
- Uncertainty or hedging ("X might be Y") vs a firm claim.

Respond ONLY with valid JSON matching this exact schema:
{
  "verdict": true | false,
  "type": "factual" | "temporal" | "none",
  "score": <float 0.0-1.0>,
  "reasoning": "<one concise sentence>"
}

Rules:
- verdict true iff type is factual or temporal (never true + none).
- verdict false iff type is none.
- score reflects your confidence: 0.9+ = clear contradiction, 0.5-0.9 = likely,
  0.0-0.5 = uncertain or no contradiction.
- reasoning must be one sentence, no longer.
- No text outside the JSON object.
"""

_JUDGE_USER_TEMPLATE = """\
Passage A:
{text_a}

Passage B:
{text_b}
"""

DEFAULT_CLAUDE_MODEL = "claude-sonnet-4-6"
_MAX_RETRIES = 2


def _load_dotenv_if_present() -> None:
    """Load .env from the repo root if python-dotenv is installed."""
    try:
        from dotenv import load_dotenv

        # Walk up from this file to the repo root (src/wikilens → src → repo).
        env_path = Path(__file__).parent.parent.parent / ".env"
        if env_path.exists():
            load_dotenv(env_path, override=False)
    except ImportError:
        pass


def _parse_verdict(raw: str) -> JudgeVerdict:
    """Parse and validate the model's JSON response into a JudgeVerdict.

    Raises ``ValueError`` on malformed or schema-violating JSON so the
    caller can retry or count as an abstention.
    """
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"judge response is not valid JSON: {e}") from e

    required = {"verdict", "type", "score", "reasoning"}
    missing = required - doc.keys()
    if missing:
        raise ValueError(f"judge response missing keys: {missing}")

    return JudgeVerdict(
        verdict=bool(doc["verdict"]),
        type=doc["type"],
        score=float(doc["score"]),
        reasoning=str(doc["reasoning"]),
    )


class ClaudeJudge:
    """Claude-backed contradiction judge using the Anthropic Messages API.

    Loads ``ANTHROPIC_API_KEY`` from env (auto-loads ``.env`` at repo root
    via python-dotenv if present). Uses JSON mode via a strict system prompt
    — no tool use, no streaming, just one synchronous call per pair.

    ``max_tokens`` is intentionally small: the schema is compact and we
    want to avoid runaway completions that inflate cost.
    """

    name = "claude"

    def __init__(
        self,
        model: str = DEFAULT_CLAUDE_MODEL,
        max_tokens: int = 256,
    ):
        _load_dotenv_if_present()
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise EnvironmentError(
                "ANTHROPIC_API_KEY is not set. "
                "Export it in your shell or add it to .env at the repo root."
            )
        try:
            import anthropic as _anthropic
        except ImportError as e:
            raise ImportError(
                "The 'anthropic' package is required for ClaudeJudge. "
                "Install it with: pip install -e '.[judge]'"
            ) from e

        self._client = _anthropic.Anthropic(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens
        self.calls: int = 0
        self.abstentions: int = 0

    def score_pair(self, text_a: str, text_b: str) -> JudgeVerdict:
        """Call Claude once per pair. Retries on malformed JSON up to _MAX_RETRIES."""
        self.calls += 1
        user_content = _JUDGE_USER_TEMPLATE.format(text_a=text_a, text_b=text_b)
        last_err: Exception | None = None

        for attempt in range(_MAX_RETRIES + 1):
            stricter = attempt > 0
            system = (
                _JUDGE_SYSTEM_PROMPT
                + (
                    "\nCRITICAL: Your previous response was not valid JSON. "
                    "Output ONLY the JSON object, nothing else."
                    if stricter
                    else ""
                )
            )
            response = self._client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=system,
                messages=[{"role": "user", "content": user_content}],
            )
            raw = response.content[0].text.strip()
            try:
                return _parse_verdict(raw)
            except ValueError as e:
                last_err = e
                continue

        # All retries exhausted — count as abstention (no contradiction).
        self.abstentions += 1
        return JudgeVerdict(
            verdict=False,
            type="none",
            score=0.0,
            reasoning=f"judge abstained after {_MAX_RETRIES + 1} attempts: {last_err}",
        )


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
