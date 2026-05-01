"""Pluggable LLM drafter interface for answer generation (P6).

Mirrors ``generator.py`` / ``judge.py``: separates the cognitive kernel
(the reasoning LLM) from the control flow (retrieval, pipeline, CLI).
Every concrete drafter exposes ``draft_stub`` and returns a plain markdown
string that the pipeline wraps into an ``AnswerDraft``.

Phase 6.1 ships ``MockDrafter``. Phase 6.2 ships ``OpenAIDrafter`` and
``ClaudeDrafter``.

The drafter is intentionally narrow: it takes a gap question plus a list of
supporting chunk texts (already retrieved + ranked by the pipeline) and
returns *only* the markdown body — frontmatter and wikilinks are assembled
by ``answer_format.py``. This keeps each piece independently testable.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from wikilens._env import load_dotenv_if_present


@dataclass(frozen=True)
class DraftInput:
    """All the information a drafter needs per gap.

    ``chunks`` are ordered by retrieval rank (1 = best). The drafter prompt
    is built from these; no raw vectors are ever passed to the model.

    ``is_external_research`` signals that the vault has insufficient
    coverage for this gap (retrieved count < ``--min-supporting``). The
    drafter should emit the "external research" stub variant rather than
    synthesizing from thin evidence.
    """

    gap_question: str
    suggested_note_title: str
    rationale: str
    chunks: tuple[tuple[str, str, str], ...]  # (chunk_id, source_rel, text)
    is_external_research: bool = False


@runtime_checkable
class Drafter(Protocol):
    """Protocol every drafter backend implements.

    ``draft_stub`` returns *only* the markdown body (the five sections from
    §D4 of the SDD, excluding frontmatter). Frontmatter is assembled by the
    formatter so it can be deterministically generated from the pipeline's
    own metadata without trusting the model to emit valid YAML.

    The caller passes ``DraftInput``; the drafter owns its own prompt, model,
    and transport. Swapping ``MockDrafter`` for ``OpenAIDrafter`` never
    forces changes upstream.
    """

    name: str

    def draft_stub(self, draft_input: DraftInput) -> str:
        """Return the markdown body for this gap stub."""
        ...


# ─── System prompt ────────────────────────────────────────────────────────────

_DRAFTER_SYSTEM_PROMPT = """\
You are a knowledge-base assistant writing a note stub for a personal Obsidian vault.

You will be given:
1. A GAP QUESTION: a question the vault implies but does not answer.
2. SUPPORTING CHUNKS: relevant passages retrieved from the vault, each labelled
   with a chunk ID and source file.

Your task is to write a structured note stub with EXACTLY these four sections:

## What the vault says
Synthesize what the supporting chunks tell us. EVERY declarative sentence must
end with a footnote reference in the form [^N] (N = integer, starting from 1).
Do not invent any facts not present in the supplied chunks.
If the vault has no relevant content (is_external_research = true), write one
sentence: "The vault has no relevant coverage for this question."

## Evidence gaps
List (as bullet points) the specific concepts, mechanisms, or facts that the
vault does NOT cover but that a complete answer would need.
IMPORTANT: Use your own domain knowledge to name the SPECIFIC missing concepts
— do NOT write vague phrases like "the mechanism is not described" or "more
detail is needed". Name the actual concepts: e.g., "RuBisCO catalysis and
the three phases (carboxylation, reduction, regeneration)" or "the Z-scheme
electron flow from PSII to PSI". This section is the gap-closing work; be
precise enough that a human reader knows exactly what to research.
For external-research stubs, suggest external source types (no fabricated URLs).

## Related notes
Leave this section COMPLETELY BLANK (no text, no placeholder, no "EMPTY").
The pipeline will insert [[wikilinks]] automatically.

## Citations
For each [^N] reference used above, write one entry using EXACTLY this format
(backticks around the chunk ID are required):
[^N]: `<chunk_id>` — "<first 15 words of the chunk text>..."

Example:
[^1]: `abc123def456` — "Light reactions produce ATP and NADPH in the thylakoid..."

Rules:
- Do NOT emit YAML frontmatter (the pipeline adds it).
- Do NOT emit a level-1 heading (the pipeline adds it from the note title).
- Do NOT add any text outside the four sections above.
- Do NOT write anything in the Related notes section — leave it completely empty.
- The section headers must be exactly as shown (## What the vault says, etc.).
- Chunk IDs in Citations MUST be wrapped in backticks: `chunk_id`.
- Only cite chunk IDs that appear in the SUPPORTING CHUNKS input.
- STRICT: Every claim in "What the vault says" must be a DIRECT quote or very
  close paraphrase of what the cited chunk actually says. Do NOT synthesize or
  infer beyond the chunk's explicit text. If you are not certain a chunk supports
  a sentence, move that claim to "Evidence gaps" instead.
- If the vault has no relevant content for the gap question, write the single
  sentence "The vault has no relevant coverage for this question." with NO
  footnote citations, and leave the Citations section empty with just
  "_No citations — external research required._"
- Start your response with "## What the vault says".
"""

_DRAFTER_USER_TEMPLATE = """\
GAP QUESTION: {gap_question}

SUPPORTING CHUNKS ({n} chunks):
{passages}

is_external_research: {is_external_research}

Write the stub body now.
"""

_DRAFTER_EXTERNAL_RESEARCH_TEMPLATE = """\
GAP QUESTION: {gap_question}

The vault has insufficient coverage for this question \
(fewer than the required minimum of supporting chunks were retrieved).
Write the external-research variant stub.
"""

_MAX_RETRIES = 2
_MAX_TOKENS = 1536


def _format_passages(chunks: tuple[tuple[str, str, str], ...]) -> str:
    parts = []
    for chunk_id, source_rel, text in chunks:
        snippet = text.strip().replace("\n", " ")
        if len(snippet) > 500:
            snippet = snippet[:500] + "..."
        parts.append(f"[{chunk_id}] ({source_rel})\n{snippet}")
    return "\n\n".join(parts)


def _validate_body(body: str) -> bool:
    """Light structural check — four required section headers present."""
    required = [
        "## What the vault says",
        "## Evidence gaps",
        "## Related notes",
        "## Citations",
    ]
    return all(h in body for h in required)


# ─── MockDrafter ──────────────────────────────────────────────────────────────


class MockDrafter:
    """Deterministic stand-in for unit tests and ``--judge none`` dry-runs.

    Returns a minimal valid stub body containing all four required sections.
    If ``bodies`` is provided, cycles through them; otherwise emits a fixed
    template so the plumbing path (load → retrieve → draft → format) runs
    end-to-end without any model loading or API calls.
    """

    name = "mock"

    def __init__(self, bodies: list[str] | None = None):
        self._bodies = list(bodies) if bodies else []
        self._idx = 0
        self.calls: int = 0

    def draft_stub(self, draft_input: DraftInput) -> str:
        self.calls += 1

        if self._bodies:
            body = self._bodies[self._idx % len(self._bodies)]
            self._idx += 1
            return body

        if draft_input.is_external_research:
            return (
                "## What the vault says\n\n"
                "The vault has no relevant coverage for this question.\n\n"
                "## Evidence gaps\n\n"
                "- External sources required to answer this question.\n\n"
                "## Related notes\n\n"
                "## Citations\n\n"
                "_No citations — external research required._\n"
            )

        # Build minimal body from first chunk (if any).
        if draft_input.chunks:
            cid, _src, text = draft_input.chunks[0]
            snippet = text.strip().replace("\n", " ")[:80]
            return (
                "## What the vault says\n\n"
                f"The vault notes that {snippet}[^1]\n\n"
                "## Evidence gaps\n\n"
                f"- mock-gap: The vault does not fully answer: {draft_input.gap_question}\n\n"
                "## Related notes\n\n"
                "## Citations\n\n"
                f"[^1]: `{cid}` — \"{snippet[:60]}...\"\n"
            )

        return (
            "## What the vault says\n\n"
            "No supporting chunks were available.\n\n"
            "## Evidence gaps\n\n"
            f"- mock-gap: {draft_input.gap_question}\n\n"
            "## Related notes\n\n"
            "## Citations\n\n"
            "_No citations._\n"
        )


# ─── OpenAIDrafter ─────────────────────────────────────────────────────────────


DEFAULT_OPENAI_MODEL = "gpt-4o"


class OpenAIDrafter:
    """OpenAI-backed stub drafter using Chat Completions API.

    Loads ``OPENAI_API_KEY`` from env (auto-loads ``.env`` via
    python-dotenv). One synchronous call per gap; retries on malformed
    structure up to ``_MAX_RETRIES``.
    """

    name = "openai"

    def __init__(
        self,
        model: str = DEFAULT_OPENAI_MODEL,
        max_tokens: int = _MAX_TOKENS,
    ):
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
                "The 'openai' package is required for OpenAIDrafter. "
                "Install it with: pip install -e '.[judge]'"
            ) from e

        self._client = _openai.OpenAI(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens
        self.calls: int = 0
        self.abstentions: int = 0

    def draft_stub(self, draft_input: DraftInput) -> str:
        self.calls += 1

        if draft_input.is_external_research:
            user_content = _DRAFTER_EXTERNAL_RESEARCH_TEMPLATE.format(
                gap_question=draft_input.gap_question,
            )
        else:
            passages = _format_passages(draft_input.chunks)
            user_content = _DRAFTER_USER_TEMPLATE.format(
                gap_question=draft_input.gap_question,
                n=len(draft_input.chunks),
                passages=passages,
                is_external_research=draft_input.is_external_research,
            )

        last_err: Exception | None = None
        system = _DRAFTER_SYSTEM_PROMPT

        for attempt in range(_MAX_RETRIES + 1):
            if attempt > 0:
                system += (
                    "\nCRITICAL: Your previous response was missing required section headers. "
                    "Start with '## What the vault says' and include all four sections."
                )
            response = self._client.chat.completions.create(
                model=self._model,
                max_tokens=self._max_tokens,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_content},
                ],
            )
            body = response.choices[0].message.content.strip()
            if _validate_body(body):
                return body
            last_err = ValueError(f"missing required sections in draft: {body[:200]!r}")

        self.abstentions += 1
        _ = last_err
        return _fallback_stub(draft_input)


# ─── ClaudeDrafter ─────────────────────────────────────────────────────────────


DEFAULT_CLAUDE_MODEL = "claude-sonnet-4-6"


class ClaudeDrafter:
    """Claude-backed stub drafter using the Anthropic Messages API.

    Loads ``ANTHROPIC_API_KEY`` from env. One synchronous call per gap;
    retries on malformed structure up to ``_MAX_RETRIES``.
    """

    name = "claude"

    def __init__(
        self,
        model: str = DEFAULT_CLAUDE_MODEL,
        max_tokens: int = _MAX_TOKENS,
    ):
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
                "The 'anthropic' package is required for ClaudeDrafter. "
                "Install it with: pip install -e '.[judge]'"
            ) from e

        self._client = _anthropic.Anthropic(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens
        self.calls: int = 0
        self.abstentions: int = 0

    def draft_stub(self, draft_input: DraftInput) -> str:
        self.calls += 1

        if draft_input.is_external_research:
            user_content = _DRAFTER_EXTERNAL_RESEARCH_TEMPLATE.format(
                gap_question=draft_input.gap_question,
            )
        else:
            passages = _format_passages(draft_input.chunks)
            user_content = _DRAFTER_USER_TEMPLATE.format(
                gap_question=draft_input.gap_question,
                n=len(draft_input.chunks),
                passages=passages,
                is_external_research=draft_input.is_external_research,
            )

        last_err: Exception | None = None
        system = _DRAFTER_SYSTEM_PROMPT

        for attempt in range(_MAX_RETRIES + 1):
            if attempt > 0:
                system += (
                    "\nCRITICAL: Your previous response was missing required section headers. "
                    "Start with '## What the vault says' and include all four sections."
                )
            response = self._client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=system,
                messages=[{"role": "user", "content": user_content}],
            )
            body = response.content[0].text.strip()
            if _validate_body(body):
                return body
            last_err = ValueError(f"missing required sections in draft: {body[:200]!r}")

        self.abstentions += 1
        _ = last_err
        return _fallback_stub(draft_input)


def _fallback_stub(draft_input: DraftInput) -> str:
    """Last-resort stub emitted when all retries are exhausted.

    Always structurally valid (four sections) so downstream formatters
    don't crash. Marked with an obvious [DRAFT FAILED] header so the
    user knows this is a placeholder.
    """
    return (
        "## What the vault says\n\n"
        "[DRAFT FAILED — all retries exhausted. Re-run with --verbose to debug.]\n\n"
        "## Evidence gaps\n\n"
        f"- {draft_input.gap_question}\n\n"
        "## Related notes\n\n"
        "## Citations\n\n"
        "_No citations._\n"
    )
