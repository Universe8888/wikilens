"""Answer drafting pipeline — retrieve → draft → attribute (M6).

Extracted from ``answer.py`` to keep both files under the 500-line limit.
The pipeline parallelizes ONLY the drafter LLM calls (Phase 2); retrieval
and attribution checking stay single-threaded by design.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from wikilens.answer import (
    AnswerDraft,
    EvidenceStrength,
    GapInput,
    check_attribution,
    retrieve_support,
)

if TYPE_CHECKING:
    from wikilens.drafter import Drafter
    from wikilens.embed import Embedder
    from wikilens.query import Mode
    from wikilens.rerank import Reranker
    from wikilens.store import VectorStore


def draft_answers(
    gaps: list[GapInput],
    store: VectorStore,
    embedder: Embedder,
    drafter: Drafter,
    *,
    top_k: int = 8,
    mode: Mode = "rerank",
    reranker: Reranker | None = None,
    min_supporting: int = 2,
    sample: int | None = None,
    drafter_model: str = "",
    workers: int = 1,
) -> list[AnswerDraft]:
    """End-to-end pipeline: per-gap retrieve → classify → draft → check.

    For each gap in ``gaps`` (up to ``sample`` if set):
    - Retrieve supporting chunks via ``retrieve_support``.
    - If retrieved count < ``min_supporting``: emit an external-research
      stub (no drafter call).
    - Otherwise: call ``drafter.draft_stub``, run ``check_attribution``,
      classify evidence_strength as "strong" or "thin" based on the
      attribution report.

    Returns one ``AnswerDraft`` per gap — including external-research and
    skipped variants — so the report is always complete and the CLI can
    report the correct exit code.

    ``drafter_model`` is a display string only (the drafter owns its own
    model internally); pass ``drafter._model`` or ``""`` from the CLI.

    ``workers`` (M6) parallelizes only the ``drafter.draft_stub`` LLM calls.
    Retrieval (embedding + LanceDB) deliberately stays on the main thread —
    those libraries are not known thread-safe for concurrent access — so the
    pipeline is: (1) retrieve serially + build DraftInputs, (2) parallel_map
    the draft calls in gap order, (3) attribution-check + assemble serially.
    The drafts list keeps input gap order for any worker count.
    """
    from wikilens.drafter import DraftInput
    from wikilens.executor import parallel_map

    to_process = gaps if sample is None else gaps[:sample]

    # Phase 1 (serial, main thread): retrieve support + build draft inputs.
    retrieved: list[tuple[list, DraftInput, bool]] = []
    for gap in to_process:
        chunks = retrieve_support(
            gap, store, embedder, top_k=top_k, mode=mode, reranker=reranker,
        )
        is_external = len(chunks) < min_supporting
        draft_input = DraftInput(
            gap_question=gap.gap_question,
            suggested_note_title=gap.suggested_note_title,
            rationale=gap.rationale,
            chunks=tuple((c.chunk_id, c.source_rel, c.text) for c in chunks),
            is_external_research=is_external,
        )
        retrieved.append((chunks, draft_input, is_external))

    # Phase 2 (parallel): the drafter LLM call per gap, preserving gap order.
    bodies = parallel_map(
        lambda item: drafter.draft_stub(item[1]),
        retrieved,
        max_workers=workers,
    )

    # Phase 3 (serial): attribution check + evidence classification + assemble.
    drafts: list[AnswerDraft] = []
    for gap, (chunks, _draft_input, is_external), body in zip(
        to_process, retrieved, bodies, strict=True
    ):
        retrieved_ids = {c.chunk_id for c in chunks}
        attr_report, citations = check_attribution(body, retrieved_ids)

        if is_external:
            strength: EvidenceStrength = "external-research"
        elif not attr_report.is_clean or attr_report.attribution_rate < 0.5:
            strength = "thin"
        else:
            strength = "strong"

        drafts.append(
            AnswerDraft(
                gap=gap,
                supporting_chunks=tuple(chunks),
                evidence_strength=strength,
                body_markdown=body,
                citations=citations,
                attribution=attr_report,
                drafter_name=drafter.name,
                model=drafter_model,
            )
        )

    return drafts
