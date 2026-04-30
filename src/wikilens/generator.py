"""Pluggable LLM generator interface for gap proposals (P5).

Mirrors ``judge.py``: separates the cognitive kernel (the reasoning LLM)
from the control flow (clustering, pipeline, CLI). Every concrete
generator exposes ``propose_gaps`` and returns ``GapCandidate`` records
with the same shape — swapping ``MockGenerator`` for ``ClaudeGenerator``
never forces changes upstream.

Phase 5.1 ships ``MockGenerator``. Phase 5.2 ships ``ClaudeGenerator``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


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
