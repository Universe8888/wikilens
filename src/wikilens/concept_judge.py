"""Pluggable LLM judge interface for unnamed concept detection (P9).

Mirrors drift_judge.py: separates the cognitive kernel from control flow.
Every concrete judge exposes ``propose`` and returns a ``ConceptProposal``
with the same shape — swapping ``MockConceptJudge`` for ``OpenAIConceptJudge``
never forces changes upstream.
"""

from __future__ import annotations

import json
import os
from typing import Protocol, runtime_checkable

from wikilens._env import load_dotenv_if_present
from wikilens.concepts import ConceptProposal
from wikilens.gap import ChunkPoint

_MAX_RETRIES = 2
_MAX_CHUNKS_IN_PROMPT = 10

DEFAULT_OPENAI_MODEL = "gpt-4o"
DEFAULT_CLAUDE_MODEL = "claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class ConceptJudge(Protocol):
    """Protocol every concept judge backend implements."""

    name: str

    def propose(self, chunks: list[ChunkPoint]) -> ConceptProposal:
        """Propose the unnamed concept the cluster of chunks is circling around."""
        ...


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are an expert analyst of personal knowledge bases. Your task is to
identify the unnamed concept that a cluster of notes is collectively
circling around — the concept the author clearly has in mind but has never
given a single canonical term.

Respond ONLY with valid JSON matching this exact schema:
{
  "proposed_term": "<single canonical term, 1-5 words>",
  "confidence": <float 0.0-1.0>,
  "rationale": "<one sentence, ≤ 200 characters>"
}

Rules:
- proposed_term must be a single canonical term (1–5 words), not a sentence.
- confidence 1.0 = the cluster clearly orbits one unnamed concept;
  0.0 = the cluster is too heterogeneous to name.
- rationale must be one sentence, no longer, no list items.
- No text outside the JSON object.
"""

_USER_TEMPLATE = """\
<cluster>
{chunk_blocks}
</cluster>

What is the unnamed concept these notes are all circling around?
Propose a single canonical term.
"""

_CHUNK_BLOCK_TEMPLATE = "<chunk id=\"{chunk_id}\">{text}</chunk>"


def _sanitise_xml(text: str) -> str:
    """Replace < and > with HTML entities to keep XML prompt delimiters intact."""
    return text.replace("<", "&lt;").replace(">", "&gt;")


def _build_user_content(chunks: list[ChunkPoint]) -> str:
    sample = chunks[:_MAX_CHUNKS_IN_PROMPT]
    blocks = "\n".join(
        _CHUNK_BLOCK_TEMPLATE.format(
            chunk_id=_sanitise_xml(p.chunk_id),
            text=_sanitise_xml(p.text),
        )
        for p in sample
    )
    return _USER_TEMPLATE.format(chunk_blocks=blocks)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def _parse_proposal(raw: str) -> ConceptProposal:
    """Parse the model's JSON into a ConceptProposal.

    Raises ValueError on malformed or schema-violating JSON so the caller
    can retry.
    """
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"concept judge response is not valid JSON: {e}") from e

    required = {"proposed_term", "confidence", "rationale"}
    missing = required - doc.keys()
    if missing:
        raise ValueError(f"concept judge response missing keys: {missing}")

    confidence = float(doc["confidence"])
    if not 0.0 <= confidence <= 1.0:
        raise ValueError(f"confidence must be in [0.0, 1.0], got {confidence!r}")

    return ConceptProposal(
        proposed_term=str(doc["proposed_term"]),
        confidence=confidence,
        rationale=str(doc["rationale"]),
    )


_FALLBACK_PROPOSAL = ConceptProposal(
    proposed_term="",
    confidence=0.0,
    rationale="judge abstained: could not produce valid JSON after retries",
)


# ---------------------------------------------------------------------------
# Mock
# ---------------------------------------------------------------------------


class MockConceptJudge:
    """Deterministic stand-in for unit tests. Never calls any API."""

    name = "mock"

    def propose(self, chunks: list[ChunkPoint]) -> ConceptProposal:
        return ConceptProposal(
            proposed_term="mock_concept",
            confidence=0.9,
            rationale="mock",
        )


# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------


class OpenAIConceptJudge:
    """OpenAI-backed concept judge using the Chat Completions API.

    Loads OPENAI_API_KEY from env (auto-loads .env at repo root via
    python-dotenv if present). One synchronous call per cluster.
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
                "The 'openai' package is required for OpenAIConceptJudge. "
                "Install it with: pip install -e '.[judge]'"
            ) from e

        self._client = _openai.OpenAI(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens
        self.calls: int = 0
        self.abstentions: int = 0

    def propose(self, chunks: list[ChunkPoint]) -> ConceptProposal:
        self.calls += 1
        user_content = _build_user_content(chunks)

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
                return _parse_proposal(raw)
            except ValueError:
                continue

        self.abstentions += 1
        return _FALLBACK_PROPOSAL


# ---------------------------------------------------------------------------
# Claude
# ---------------------------------------------------------------------------


class ClaudeConceptJudge:
    """Claude-backed concept judge using the Anthropic Messages API.

    Loads ANTHROPIC_API_KEY from env (auto-loads .env at repo root via
    python-dotenv if present). One synchronous call per cluster.
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
                "The 'anthropic' package is required for ClaudeConceptJudge. "
                "Install it with: pip install -e '.[judge]'"
            ) from e

        self._client = _anthropic.Anthropic(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens
        self.calls: int = 0
        self.abstentions: int = 0

    def propose(self, chunks: list[ChunkPoint]) -> ConceptProposal:
        self.calls += 1
        user_content = _build_user_content(chunks)

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
                return _parse_proposal(raw)
            except ValueError:
                continue

        self.abstentions += 1
        return _FALLBACK_PROPOSAL
