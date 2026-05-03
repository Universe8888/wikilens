"""Pluggable LLM judge interface for epistemic confidence mapping (P10).

Mirrors concept_judge.py / drift_judge.py: the cognitive kernel is separated
from control flow.  Every concrete judge exposes ``classify`` and returns a
``ConfidenceVerdict`` — swapping ``MockConfidenceJudge`` for
``OpenAIConfidenceJudge`` never forces changes upstream.
"""

from __future__ import annotations

import json
import os
import re
from typing import Protocol, runtime_checkable

from wikilens._env import load_dotenv_if_present
from wikilens.confidence import ConfidenceVerdict

_MAX_RETRIES = 2

DEFAULT_OPENAI_MODEL = "gpt-4o"
DEFAULT_CLAUDE_MODEL = "claude-sonnet-4-6"

# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class ConfidenceJudge(Protocol):
    """Protocol every confidence judge backend implements."""

    name: str

    def classify(self, claim: str, note_context: str) -> ConfidenceVerdict:
        """Classify one claim on the 1-5 epistemic confidence scale."""
        ...


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are an expert analyst of epistemic markers in personal knowledge notes.
Classify the confidence level of a single claim on this exact scale:

  1 = speculation   — the author uses an explicit hedge word or phrase:
                      "I think", "I suspect", "maybe", "it seems", "I wonder",
                      "I'm not sure", "probably", "might", "could be", "I feel".
                      ONLY assign L1 when one of these hedge phrases is present.

  2 = conjecture    — stated as a flat assertion with no support, no reasoning
                      chain, no inference connective, and no attribution.
                      Use L2 only when L3, L4, and L5 do not apply.

  3 = inference     — the claim is reasoned from other evidence. Signals:
                      "because", "given that", "therefore", "this is why",
                      "which is why", "must have been", "this tracks with",
                      a wikilink used as evidence, or a cause→effect chain.
                      First-person voice alone does NOT make a claim L1.

  4 = attributed    — explicitly credits a named person, work, or organisation
                      (author, book title, study, named body). Attribution can
                      appear as an appositive ("Tacitus, writing under…") or a
                      parenthetical — look for any proper-noun source framing.

  5 = verified      — textbook-empirical or replicated scientific consensus.
                      Strong signals: physics constants, basic biology, or
                      facts stated without hedge or citation because they are
                      universally established.

Decision order: check L5 → L4 → L3 → L1 → L2.
Assign L2 only after ruling out all others.

Respond ONLY with valid JSON:
{
  "level": <integer 1-5>,
  "rationale": "<one sentence, <= 200 characters>",
  "confidence": <float 0.0-1.0>
}

Rules:
- level must be an integer 1, 2, 3, 4, or 5.
- rationale must explain which signal you found (or did not find).
- confidence is how certain you are of your own classification (1.0 = certain).
- No text outside the JSON object.
"""

_USER_TEMPLATE = """\
<context>
{context}
</context>

<claim>
{claim}
</claim>

Classify the epistemic confidence level of the <claim> (1-5).
Use the <context> only to check for cross-references or hedges in nearby sentences.
"""


def _sanitise_xml(text: str) -> str:
    """Replace < and > with HTML entities to keep XML prompt delimiters intact."""
    return text.replace("<", "&lt;").replace(">", "&gt;")


def _build_user_content(claim: str, note_context: str) -> str:
    return _USER_TEMPLATE.format(
        context=_sanitise_xml(note_context),
        claim=_sanitise_xml(claim),
    )


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def _strip_fences(raw: str) -> str:
    """Remove markdown code fences (```json ... ``` or ``` ... ```) if present."""
    m = re.match(r"^```(?:json)?\s*([\s\S]*?)\s*```$", raw.strip())
    return m.group(1) if m else raw


def _parse_verdict(raw: str) -> ConfidenceVerdict:
    """Parse the model's JSON into a ConfidenceVerdict.

    Raises ValueError on malformed or schema-violating JSON so the caller
    can retry.
    """
    raw = _strip_fences(raw)
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"confidence judge response is not valid JSON: {e}") from e

    required = {"level", "rationale", "confidence"}
    missing = required - doc.keys()
    if missing:
        raise ValueError(f"confidence judge response missing keys: {missing}")

    level = int(doc["level"])
    if level not in (1, 2, 3, 4, 5):
        raise ValueError(f"level must be 1-5, got {level!r}")

    confidence = float(doc["confidence"])
    if not 0.0 <= confidence <= 1.0:
        raise ValueError(f"confidence must be in [0.0, 1.0], got {confidence!r}")

    return ConfidenceVerdict(
        level=level,
        rationale=str(doc["rationale"]),
        confidence=confidence,
    )


# Fallback returned when all retries are exhausted.
# level=3 (inference) is the "neutral" midpoint — not flagged as low-confidence.
_FALLBACK_VERDICT = ConfidenceVerdict(
    level=3,
    rationale="judge abstained: could not produce valid JSON after retries",
    confidence=0.0,
)


# ---------------------------------------------------------------------------
# Mock
# ---------------------------------------------------------------------------


class MockConfidenceJudge:
    """Deterministic stand-in for unit tests. Never calls any API."""

    name = "mock"

    def classify(self, claim: str, note_context: str) -> ConfidenceVerdict:  # noqa: ARG002
        claim_lower = claim.lower()
        # Detect explicit hedges for L1
        hedges = ("i think", "maybe", "i suspect", "it seems", "i wonder",
                  "i feel", "i'm not sure", "probably", "might be", "could be")
        if any(h in claim_lower for h in hedges):
            return ConfidenceVerdict(level=1, rationale="mock: explicit hedge detected", confidence=0.9)  # noqa: E501
        return ConfidenceVerdict(level=3, rationale="mock: no hedge, treated as inference", confidence=0.8)  # noqa: E501


# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------


class OpenAIConfidenceJudge:
    """OpenAI-backed confidence judge using the Chat Completions API.

    Loads OPENAI_API_KEY from env (auto-loads .env at repo root via
    python-dotenv if present). One synchronous call per claim.
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
                "The 'openai' package is required for OpenAIConfidenceJudge. "
                "Install it with: pip install -e '.[judge]'"
            ) from e

        self._client = _openai.OpenAI(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens
        self.calls: int = 0
        self.abstentions: int = 0

    def classify(self, claim: str, note_context: str) -> ConfidenceVerdict:
        self.calls += 1
        user_content = _build_user_content(claim, note_context)

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
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_content},
                ],
            )
            content = response.choices[0].message.content
            raw = (content or "").strip()
            try:
                return _parse_verdict(raw)
            except ValueError:
                continue

        self.abstentions += 1
        return _FALLBACK_VERDICT


# ---------------------------------------------------------------------------
# Claude
# ---------------------------------------------------------------------------


class ClaudeConfidenceJudge:
    """Claude-backed confidence judge using the Anthropic Messages API.

    Loads ANTHROPIC_API_KEY from env (auto-loads .env at repo root via
    python-dotenv if present). One synchronous call per claim.
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
                "The 'anthropic' package is required for ClaudeConfidenceJudge. "
                "Install it with: pip install -e '.[judge]'"
            ) from e

        self._client = _anthropic.Anthropic(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens
        self.calls: int = 0
        self.abstentions: int = 0

    def classify(self, claim: str, note_context: str) -> ConfidenceVerdict:
        self.calls += 1
        user_content = _build_user_content(claim, note_context)

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
            except ValueError:
                continue

        self.abstentions += 1
        return _FALLBACK_VERDICT
