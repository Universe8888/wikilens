"""Pluggable LLM judge interface for temporal drift scoring (P8).

Mirrors judge.py (P4): separates the cognitive kernel from the control flow.
Every concrete judge exposes ``score_pair`` and returns a ``DriftVerdict``
with the same shape — swapping ``MockDriftJudge`` for ``OpenAIDriftJudge``
never forces changes upstream.

Phase 8.3 ships MockDriftJudge, OpenAIDriftJudge, and ClaudeDriftJudge.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

from wikilens._env import load_dotenv_if_present

DriftType = Literal["reversal", "refinement", "scope_change", "none"]
ALL_DRIFT_TYPES: tuple[DriftType, ...] = ("reversal", "refinement", "scope_change", "none")

DEFAULT_CLAUDE_MODEL = "claude-sonnet-4-6"
DEFAULT_OPENAI_MODEL = "gpt-4o"
_MAX_RETRIES = 2


# ---------------------------------------------------------------------------
# Verdict dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DriftVerdict:
    """Structured output of one drift judge call.

    Attributes:
        drift: True iff the judge considers this a genuine belief change
            (type != none AND score >= caller's --min-score threshold).
        type: the class of change. "none" iff drift is False.
        score: judge confidence on a 1–5 integer scale. 1 = no drift,
            5 = clear belief change. Caller applies --min-score threshold.
        reasoning: one-sentence rationale, ≤ 200 chars.
    """

    drift: bool
    type: DriftType
    score: int
    reasoning: str

    def __post_init__(self) -> None:
        if self.type not in ALL_DRIFT_TYPES:
            raise ValueError(f"type must be one of {ALL_DRIFT_TYPES}, got {self.type!r}")
        if not 1 <= self.score <= 5:
            raise ValueError(f"score must be in [1, 5], got {self.score!r}")
        if self.drift and self.type == "none":
            raise ValueError("drift=True requires type in {reversal, refinement, scope_change}")
        if not self.drift and self.type != "none":
            raise ValueError("drift=False requires type='none'")


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class DriftJudge(Protocol):
    """Protocol every drift judge backend implements."""

    name: str

    def score_pair(
        self,
        note: str,
        before_claim: str,
        before_date: str,
        after_claim: str,
        after_date: str,
    ) -> DriftVerdict:
        """Judge whether the author's position changed between before and after."""
        ...


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are an expert analyst of personal knowledge bases. Your task is to determine
whether an author's stated belief or position genuinely changed between two
revisions of the same note.

Drift types:
- reversal: The author's position flipped or was directly contradicted.
  Before: "X causes Y."  After: "X correlates with Y but does not cause it."
- refinement: The claim was softened, hedged, or scoped — still a belief change.
  Before: "Meditation is proven to reduce anxiety."
  After: "Some studies suggest meditation may help with anxiety, though replication is mixed."
- scope_change: The claim was narrowed or broadened in a meaningful way.
  Before: "AI will replace all coders."  After: "AI will automate routine coding tasks."
- none: No genuine belief change. Includes:
  - Rephrasing / voice change that preserves the same position.
  - Typo or grammar fix.
  - Adding an illustrative example without changing the claim.
  - Reordering list items.
  - A more specific restatement that does not contradict the original.

Respond ONLY with valid JSON matching this exact schema:
{
  "drift": true | false,
  "type": "reversal" | "refinement" | "scope_change" | "none",
  "score": <integer 1-5>,
  "reasoning": "<one sentence, ≤ 200 characters>"
}

Rules:
- drift true iff type is reversal, refinement, or scope_change.
- drift false iff type is none.
- score 5 = clear, unambiguous belief change; 1 = clearly the same position; 3 = borderline.
- reasoning must be one sentence, no longer, no list items.
- No text outside the JSON object.
"""

_USER_TEMPLATE = """\
<note>{note}</note>

<before>
<date>{before_date}</date>
<claim>{before_claim}</claim>
</before>

<after>
<date>{after_date}</date>
<claim>{after_claim}</claim>
</after>
"""


def _sanitise_xml(text: str) -> str:
    """Strip XML-like tokens that could confuse the prompt delimiters.

    User content (note paths, claim sentences) is interpolated into an XML-
    tagged template. A claim like "A > B" or "see <note>" would break the
    delimiter structure and let a malicious vault mount a prompt-injection
    attack. Defence: replace < and > with their HTML entities. The judge
    still reads the text correctly; the delimiters stay inviolate.
    """
    return text.replace("<", "&lt;").replace(">", "&gt;")


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def _parse_verdict(raw: str) -> DriftVerdict:
    """Parse and validate the model's JSON response into a DriftVerdict.

    Raises ValueError on malformed or schema-violating JSON so the caller
    can retry or count as abstention.
    """
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"drift judge response is not valid JSON: {e}") from e

    required = {"drift", "type", "score", "reasoning"}
    missing = required - doc.keys()
    if missing:
        raise ValueError(f"drift judge response missing keys: {missing}")

    return DriftVerdict(
        drift=bool(doc["drift"]),
        type=doc["type"],
        score=int(doc["score"]),
        reasoning=str(doc["reasoning"]),
    )


# ---------------------------------------------------------------------------
# Mock
# ---------------------------------------------------------------------------


class MockDriftJudge:
    """Deterministic stand-in for --judge none and unit tests.

    Returns verdicts from a pre-seeded sequence, cycling when exhausted.
    Default (no sequence): returns a fixed "no drift" verdict so the
    full pipeline path can be exercised without any API calls.
    """

    name = "mock"

    def __init__(self, verdicts: list[DriftVerdict] | None = None):
        self._verdicts: list[DriftVerdict] = list(verdicts) if verdicts else []
        self._idx = 0
        self.calls: int = 0
        self.abstentions: int = 0

    def score_pair(
        self,
        note: str,
        before_claim: str,
        before_date: str,
        after_claim: str,
        after_date: str,
    ) -> DriftVerdict:
        self.calls += 1
        if not self._verdicts:
            return DriftVerdict(
                drift=False,
                type="none",
                score=1,
                reasoning="mock judge: no seeded verdict",
            )
        v = self._verdicts[self._idx % len(self._verdicts)]
        self._idx += 1
        return v


# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------


class OpenAIDriftJudge:
    """OpenAI-backed drift judge using the Chat Completions API.

    Loads OPENAI_API_KEY from env (auto-loads .env at repo root via
    python-dotenv if present). One synchronous call per pair.
    """

    name = "openai"

    def __init__(self, model: str = DEFAULT_OPENAI_MODEL, max_tokens: int = 256):
        load_dotenv_if_present()
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise OSError(
                "OPENAI_API_KEY is not set. "
                "Export it in your shell or add it to .env at the repo root."
            )
        try:
            import openai as _openai
        except ImportError as e:
            raise ImportError(
                "The 'openai' package is required for OpenAIDriftJudge. "
                "Install it with: pip install -e '.[judge]'"
            ) from e

        self._client = _openai.OpenAI(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens
        self.calls: int = 0
        self.abstentions: int = 0

    def score_pair(
        self,
        note: str,
        before_claim: str,
        before_date: str,
        after_claim: str,
        after_date: str,
    ) -> DriftVerdict:
        self.calls += 1
        user_content = _USER_TEMPLATE.format(
            note=_sanitise_xml(note),
            before_claim=_sanitise_xml(before_claim),
            before_date=_sanitise_xml(before_date),
            after_claim=_sanitise_xml(after_claim),
            after_date=_sanitise_xml(after_date),
        )
        last_err: Exception | None = None

        for attempt in range(_MAX_RETRIES + 1):
            system = _SYSTEM_PROMPT + (
                "\nCRITICAL: Your previous response was not valid JSON. "
                "Output ONLY the JSON object, nothing else."
                if attempt > 0
                else ""
            )
            response = self._client.chat.completions.create(
                model=self._model,
                max_tokens=self._max_tokens,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_content},
                ],
            )
            content = response.choices[0].message.content
            raw = (content or "").strip()
            try:
                return _parse_verdict(raw)
            except ValueError as e:
                last_err = e
                continue

        self.abstentions += 1
        return DriftVerdict(
            drift=False,
            type="none",
            score=1,
            reasoning=f"judge abstained after {_MAX_RETRIES + 1} attempts: {last_err}",
        )


# ---------------------------------------------------------------------------
# Claude
# ---------------------------------------------------------------------------


class ClaudeDriftJudge:
    """Claude-backed drift judge using the Anthropic Messages API.

    Loads ANTHROPIC_API_KEY from env (auto-loads .env at repo root via
    python-dotenv if present). One synchronous call per pair.
    """

    name = "claude"

    def __init__(self, model: str = DEFAULT_CLAUDE_MODEL, max_tokens: int = 256):
        load_dotenv_if_present()
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise OSError(
                "ANTHROPIC_API_KEY is not set. "
                "Export it in your shell or add it to .env at the repo root."
            )
        try:
            import anthropic as _anthropic
        except ImportError as e:
            raise ImportError(
                "The 'anthropic' package is required for ClaudeDriftJudge. "
                "Install it with: pip install -e '.[judge]'"
            ) from e

        self._client = _anthropic.Anthropic(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens
        self.calls: int = 0
        self.abstentions: int = 0

    def score_pair(
        self,
        note: str,
        before_claim: str,
        before_date: str,
        after_claim: str,
        after_date: str,
    ) -> DriftVerdict:
        self.calls += 1
        user_content = _USER_TEMPLATE.format(
            note=_sanitise_xml(note),
            before_claim=_sanitise_xml(before_claim),
            before_date=_sanitise_xml(before_date),
            after_claim=_sanitise_xml(after_claim),
            after_date=_sanitise_xml(after_date),
        )
        last_err: Exception | None = None

        for attempt in range(_MAX_RETRIES + 1):
            system = _SYSTEM_PROMPT + (
                "\nCRITICAL: Your previous response was not valid JSON. "
                "Output ONLY the JSON object, nothing else."
                if attempt > 0
                else ""
            )
            response = self._client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=system,
                messages=[{"role": "user", "content": user_content}],
            )
            raw = getattr(response.content[0], "text", "").strip()
            try:
                return _parse_verdict(raw)
            except ValueError as e:
                last_err = e
                continue

        self.abstentions += 1
        return DriftVerdict(
            drift=False,
            type="none",
            score=1,
            reasoning=f"judge abstained after {_MAX_RETRIES + 1} attempts: {last_err}",
        )
