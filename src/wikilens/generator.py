"""Pluggable LLM generator interface for gap proposals (P5).

Mirrors ``judge.py``: separates the cognitive kernel (the reasoning LLM)
from the control flow (clustering, pipeline, CLI). Every concrete
generator exposes ``propose_gaps`` and returns ``GapCandidate`` records
with the same shape — swapping ``MockGenerator`` for ``ClaudeGenerator``
never forces changes upstream.

Phase 5.1 ships ``MockGenerator``. Phase 5.2 ships ``ClaudeGenerator``.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from wikilens._env import load_dotenv_if_present


@dataclass(frozen=True)
class GapCandidate:
    """One gap proposal produced by a generator for a single cluster.

    Attributes:
        gap_question: the unanswered question the generator believes the
            cluster implies but doesn't answer. One concrete sentence.
        suggested_note_title: kebab-case stub the user could create to
            close the gap. No extension, no path.
        rationale: one-sentence explanation grounded in the cluster's
            own content — "these three notes describe X, but none
            mention Y."
        supporting_chunk_ids: subset of the cluster's chunk IDs that
            most directly imply the gap. Enables the Proof-Carrying
            Actions pattern — the human reviewer sees the decision
            trace, not just the conclusion.
    """

    gap_question: str
    suggested_note_title: str
    rationale: str
    supporting_chunk_ids: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.gap_question.strip():
            raise ValueError("gap_question must be non-empty")
        if not self.suggested_note_title.strip():
            raise ValueError("suggested_note_title must be non-empty")
        # kebab-case: lowercase letters, digits, and hyphens only. The
        # generator prompt enforces this too; the dataclass is the
        # last line of defense against a malformed title leaking into
        # the user's vault.
        if not _KEBAB_RE.match(self.suggested_note_title):
            raise ValueError(
                f"suggested_note_title must be kebab-case "
                f"(lowercase + digits + hyphens), got {self.suggested_note_title!r}"
            )


_KEBAB_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@dataclass(frozen=True)
class GapFinding:
    """A ``GapCandidate`` bound to its source cluster.

    The CLI report groups findings by cluster; the eval harness flattens
    them for matching against gold gaps.
    """

    cluster_id: int
    cluster_size: int
    candidate: GapCandidate


@runtime_checkable
class Generator(Protocol):
    """Protocol every generator backend implements.

    ``propose_gaps`` takes a cluster's chunk texts (ordered, with IDs)
    and returns up to ``top_k`` gap candidates. Implementations own
    their own prompt, model, and transport — the caller sees only
    ``GapCandidate`` records.

    The chunk inputs are provided as ``(chunk_id, text)`` tuples so
    the generator can cite supporting IDs in the returned candidates.
    """

    name: str

    def propose_gaps(
        self,
        cluster_chunks: list[tuple[str, str]],
        *,
        top_k: int,
    ) -> list[GapCandidate]:
        """Return up to ``top_k`` gap candidates for this cluster."""
        ...


_GENERATOR_SYSTEM_PROMPT = """\
You are an expert knowledge-base analyst. You will be given a cluster of
related notes from a personal knowledge base. Your task is to identify
UNANSWERED QUESTIONS — topics or concepts the notes clearly imply or
reference, but never actually explain or define.

Rules:
- Only propose gaps that are genuinely absent. If the answer appears anywhere
  in the provided passages, do NOT propose it as a gap.
- Each gap must be a concrete, specific question (not "what else is missing?").
- suggested_note_title must be kebab-case: lowercase letters, digits, and
  hyphens only (e.g. "calvin-cycle", "async-io-python", "treaty-of-westphalia").
- rationale must cite specific evidence from the provided passages — name the
  note or phrase that implies the gap.
- supporting_chunk_ids must be a subset of the chunk IDs given in the input.
- Return ONLY a valid JSON array (no markdown, no preamble, no trailing text).
  Start your response with "[".

JSON schema (array of up to {top_k} items):
[
  {{
    "gap_question": "<one concrete question the vault doesn't answer>",
    "suggested_note_title": "<kebab-case-stub>",
    "rationale": "<one sentence citing the evidence that implies this gap>",
    "supporting_chunk_ids": ["<chunk_id>", ...]
  }}
]
"""

_GENERATOR_USER_TEMPLATE = """\
Cluster of {n} related notes. Identify up to {top_k} unanswered questions.

<passages>
{passages}
</passages>
"""

DEFAULT_CLAUDE_MODEL = "claude-sonnet-4-6"
DEFAULT_OPENAI_MODEL = "gpt-4o"
_MAX_RETRIES = 2
_MAX_TOKENS_PER_CLUSTER = 1024


def _format_passages(cluster_chunks: list[tuple[str, str]]) -> str:
    parts = []
    for chunk_id, text in cluster_chunks:
        snippet = text.strip().replace("\n", " ")
        if len(snippet) > 400:
            snippet = snippet[:400] + "..."
        parts.append(f"[{chunk_id}]\n{snippet}")
    return "\n\n".join(parts)


def _parse_candidates(raw: str, valid_ids: set[str]) -> list[GapCandidate]:
    """Parse and validate the JSON array from the model.

    Raises ``ValueError`` on malformed or schema-violating JSON.
    Silently drops items whose ``supporting_chunk_ids`` reference unknown IDs
    (filter, not error — model may hallucinate an ID).
    """
    try:
        items = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"generator response is not valid JSON: {e}") from e

    if not isinstance(items, list):
        raise ValueError(f"generator response must be a JSON array, got {type(items).__name__}")

    out: list[GapCandidate] = []
    for item in items:
        required = {"gap_question", "suggested_note_title", "rationale"}
        missing = required - item.keys()
        if missing:
            raise ValueError(f"generator item missing keys: {missing}")
        raw_ids = item.get("supporting_chunk_ids") or []
        # Filter to only IDs that actually exist in this cluster.
        good_ids = tuple(cid for cid in raw_ids if cid in valid_ids)
        out.append(
            GapCandidate(
                gap_question=str(item["gap_question"]),
                suggested_note_title=str(item["suggested_note_title"]),
                rationale=str(item["rationale"]),
                supporting_chunk_ids=good_ids,
            )
        )
    return out


class ClaudeGenerator:
    """Claude-backed gap generator using the Anthropic Messages API.

    Loads ``ANTHROPIC_API_KEY`` from env (auto-loads ``.env`` via
    python-dotenv). Uses a structured JSON prompt — no tool use, no
    streaming, one synchronous call per cluster.
    """

    name = "claude"

    def __init__(
        self,
        model: str = DEFAULT_CLAUDE_MODEL,
        max_tokens: int = _MAX_TOKENS_PER_CLUSTER,
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
                "The 'anthropic' package is required for ClaudeGenerator. "
                "Install it with: pip install -e '.[judge]'"
            ) from e

        self._client = _anthropic.Anthropic(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens
        self.calls: int = 0
        self.abstentions: int = 0

    def propose_gaps(
        self,
        cluster_chunks: list[tuple[str, str]],
        *,
        top_k: int,
    ) -> list[GapCandidate]:
        """Call Claude once per cluster. Retries on malformed JSON up to _MAX_RETRIES."""
        self.calls += 1
        valid_ids = {cid for cid, _ in cluster_chunks}
        passages = _format_passages(cluster_chunks)
        system = _GENERATOR_SYSTEM_PROMPT.format(top_k=top_k)
        user_content = _GENERATOR_USER_TEMPLATE.format(
            n=len(cluster_chunks),
            top_k=top_k,
            passages=passages,
        )
        last_err: Exception | None = None

        for attempt in range(_MAX_RETRIES + 1):
            if attempt > 0:
                system += (
                    "\nCRITICAL: Your previous response was not a valid JSON array. "
                    'Output ONLY the JSON array, starting with "[".'
                )
            response = self._client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=system,
                messages=[{"role": "user", "content": user_content}],
            )
            raw = getattr(response.content[0], "text", "").strip()
            try:
                candidates = _parse_candidates(raw, valid_ids)
                return candidates[:top_k]
            except (ValueError, KeyError) as e:
                last_err = e
                continue

        # All retries exhausted — count as abstention (no candidates for this cluster).
        self.abstentions += 1
        _ = last_err  # consumed: available in debugger but not surfaced in output
        return []


class OpenAIGenerator:
    """OpenAI-backed gap generator using the Chat Completions API.

    Loads ``OPENAI_API_KEY`` from env (auto-loads ``.env`` via
    python-dotenv). Uses a structured JSON prompt — no tool use, no
    streaming, one synchronous call per cluster.
    """

    name = "openai"

    def __init__(
        self,
        model: str = DEFAULT_OPENAI_MODEL,
        max_tokens: int = _MAX_TOKENS_PER_CLUSTER,
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
                "The 'openai' package is required for OpenAIGenerator. "
                "Install it with: pip install -e '.[judge]'"
            ) from e

        self._client = _openai.OpenAI(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens
        self.calls: int = 0
        self.abstentions: int = 0

    def propose_gaps(
        self,
        cluster_chunks: list[tuple[str, str]],
        *,
        top_k: int,
    ) -> list[GapCandidate]:
        """Call OpenAI once per cluster. Retries on malformed JSON up to _MAX_RETRIES."""
        self.calls += 1
        valid_ids = {cid for cid, _ in cluster_chunks}
        passages = _format_passages(cluster_chunks)
        system = _GENERATOR_SYSTEM_PROMPT.format(top_k=top_k)
        user_content = _GENERATOR_USER_TEMPLATE.format(
            n=len(cluster_chunks),
            top_k=top_k,
            passages=passages,
        )
        last_err: Exception | None = None

        for attempt in range(_MAX_RETRIES + 1):
            if attempt > 0:
                system += (
                    "\nCRITICAL: Your previous response was not a valid JSON array. "
                    'Output ONLY the JSON array, starting with "[".'
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
                candidates = _parse_candidates(raw, valid_ids)
                return candidates[:top_k]
            except (ValueError, KeyError) as e:
                last_err = e
                continue

        self.abstentions += 1
        _ = last_err
        return []


class MockGenerator:
    """Deterministic stand-in used by ``--judge none`` and unit tests.

    Returns a cycling sequence of pre-seeded ``GapCandidate`` records,
    one call per cluster. If no sequence is provided, returns a single
    fixed "mock gap" so the plumbing path (cluster → generate → format)
    runs end-to-end without any model loading or API calls.
    """

    name = "mock"

    def __init__(self, candidates: list[list[GapCandidate]] | None = None):
        self._batches: list[list[GapCandidate]] = (
            list(candidates) if candidates else []
        )
        self._idx = 0
        self.calls: int = 0

    def propose_gaps(
        self,
        cluster_chunks: list[tuple[str, str]],
        *,
        top_k: int,
    ) -> list[GapCandidate]:
        self.calls += 1
        if not self._batches:
            default = GapCandidate(
                gap_question="What is the broader context that ties these notes together?",
                suggested_note_title=f"mock-gap-{self.calls}",
                rationale="mock generator: no seeded batch",
                supporting_chunk_ids=tuple(cid for cid, _ in cluster_chunks[:3]),
            )
            return [default][:top_k]
        batch = self._batches[self._idx % len(self._batches)]
        self._idx += 1
        return list(batch[:top_k])
