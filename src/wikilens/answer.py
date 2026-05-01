"""Answer Generator — consume ``gap --json`` → retrieve → draft stubs (P6).

Given the findings a prior ``wikilens gap`` run produced, this module:

1. loads the JSON file the CLI emitted (``gap_format.JSON_SCHEMA_VERSION = 1``),
2. retrieves supporting chunks from the existing vector store per gap,
3. calls a pluggable ``Drafter`` to produce a structured stub note, and
4. runs an automated attribution check that every cited sentence resolves
   to a retrieved chunk id.

The cognitive kernel lives in ``drafter.py``. The markdown/JSON
presentation lives in ``answer_format.py``. This module owns only the
plumbing — schema validation, retrieval orchestration, skip policy,
attribution parsing — so each piece stays independently testable.

Phase 6.1 ships the dataclasses + plumbing (model-free). ``OpenAIDrafter``
and ``ClaudeDrafter`` land in Phase 6.2.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from wikilens.drafter import Drafter, DraftInput
    from wikilens.embed import Embedder
    from wikilens.query import Mode
    from wikilens.rerank import Reranker
    from wikilens.store import VectorStore

# Schema version emitted by ``gap_format.format_json``.  Bump here if P5
# ever bumps its own schema — this is the only place P6 declares the contract.
GAP_JSON_SCHEMA_VERSION = 1

EvidenceStrength = Literal["strong", "thin", "external-research"]
ALL_EVIDENCE_STRENGTHS: tuple[EvidenceStrength, ...] = (
    "strong",
    "thin",
    "external-research",
)


@dataclass(frozen=True)
class GapInput:
    """One gap finding, loaded from a ``gap --json`` file.

    Mirrors the shape emitted by ``gap_format.format_json`` (schema v1)
    but strips fields the drafter doesn't need. Keeping this record
    separate from ``generator.GapFinding`` means P6's input contract
    survives even if P5's internal dataclass is refactored.
    """

    cluster_id: int
    cluster_size: int
    gap_question: str
    suggested_note_title: str
    rationale: str
    supporting_chunk_ids: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class SupportingChunk:
    """One retrieved chunk offered to the drafter as evidence.

    ``retrieval_rank`` is 1-based and preserves the order the drafter
    will see. ``source_rel`` drives wikilink basename resolution (D10).
    """

    chunk_id: str
    source_rel: str
    heading_path: tuple[str, ...]
    text: str
    retrieval_rank: int
    retrieval_score: float


@dataclass(frozen=True)
class Citation:
    """One footnote reference in a drafted stub.

    Parsed back out of drafter markdown by ``check_attribution`` and
    re-emitted verbatim by the formatter. ``footnote_id`` is the
    integer N in ``[^N]``.
    """

    footnote_id: int
    chunk_id: str
    snippet: str


@dataclass(frozen=True)
class AttributionReport:
    """Result of scanning a draft for cite-vs-support compliance.

    Produced by ``check_attribution(draft, retrieved_chunk_ids)``.
    ``attribution_rate`` is the headline automated metric (§D5 of
    ``docs/p6-plan.md``): cited_sentences / total_sentences. No LLM.

    Attributes:
        total_sentences: declarative sentence count in "What the vault
            says". Zero for ``external-research`` stubs (the section is
            replaced with a silence statement).
        cited_sentences: subset of ``total_sentences`` that carry at
            least one valid ``[^N]`` footnote.
        orphan_footnotes: ``[^N]`` references that don't resolve to any
            ``Citations`` entry.
        invalid_chunk_refs: footnote chunk ids that weren't in the
            retrieved set for this draft — the structural hallucination
            signal.
    """

    total_sentences: int
    cited_sentences: int
    orphan_footnotes: tuple[int, ...] = field(default_factory=tuple)
    invalid_chunk_refs: tuple[str, ...] = field(default_factory=tuple)

    @property
    def attribution_rate(self) -> float:
        if self.total_sentences == 0:
            return 1.0
        return self.cited_sentences / self.total_sentences

    @property
    def is_clean(self) -> bool:
        """Zero orphan footnotes and zero invalid chunk references.

        ``attribution_rate`` can still be below 1.0 on a "clean" draft —
        some sentences may legitimately not need a citation (e.g., the
        gap restatement). ``is_clean`` is the structural check only.
        """
        return not self.orphan_footnotes and not self.invalid_chunk_refs


@dataclass(frozen=True)
class AnswerDraft:
    """One drafted stub, bound to its source gap and its evidence set.

    The stub's markdown body lives in ``body_markdown``; the formatter
    consumes it verbatim when rendering the full file (frontmatter +
    body). ``supporting_chunks`` is the exact set handed to the
    drafter, preserved so the attribution check can verify citations
    without re-running retrieval.
    """

    gap: GapInput
    supporting_chunks: tuple[SupportingChunk, ...]
    evidence_strength: EvidenceStrength
    body_markdown: str
    citations: tuple[Citation, ...]
    attribution: AttributionReport
    drafter_name: str
    model: str
    skipped: bool = False
    skip_reason: str = ""


@dataclass(frozen=True)
class AnswerReport:
    """Container for one ``wikilens answer`` run.

    ``drafts`` covers every input gap — skipped gaps included, with
    ``skipped=True`` and ``skip_reason`` populated. The CLI's exit code
    (§D9) is derived from ``total_skipped``.
    """

    vault_root: str
    gaps_path: str
    drafter_name: str
    model: str
    retrieval_mode: str
    top_k: int
    min_supporting: int
    drafts: tuple[AnswerDraft, ...]

    @property
    def total_drafts(self) -> int:
        return len(self.drafts)

    @property
    def total_skipped(self) -> int:
        return sum(1 for d in self.drafts if d.skipped)

    @property
    def total_external_research(self) -> int:
        return sum(
            1 for d in self.drafts if d.evidence_strength == "external-research"
        )

    @property
    def total_drafted(self) -> int:
        """Drafts that actually ran the drafter (not skipped)."""
        return sum(1 for d in self.drafts if not d.skipped)


# ─── step 3: load_gaps ────────────────────────────────────────────────────────


def load_gaps(path: str | Path) -> list[GapInput]:
    """Parse a ``gap --json`` file and return one ``GapInput`` per finding.

    Raises ``ValueError`` for:
    - file not found / unreadable
    - invalid JSON
    - wrong ``schema_version``
    - missing required keys in any finding object
    """
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ValueError(f"gaps file not found: {path}")
    except OSError as e:
        raise ValueError(f"could not read gaps file {path}: {e}") from e

    try:
        doc = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"gaps file is not valid JSON: {e}") from e

    version = doc.get("schema_version")
    if version != GAP_JSON_SCHEMA_VERSION:
        raise ValueError(
            f"gaps file has schema_version={version!r}; "
            f"expected {GAP_JSON_SCHEMA_VERSION}. "
            "Regenerate with the current version of `wikilens gap --json`."
        )

    findings = doc.get("findings")
    if not isinstance(findings, list):
        raise ValueError("gaps file has no 'findings' array")

    required_keys = {
        "cluster_id",
        "cluster_size",
        "gap_question",
        "suggested_note_title",
        "rationale",
    }
    gaps: list[GapInput] = []
    for i, item in enumerate(findings):
        missing = required_keys - item.keys()
        if missing:
            raise ValueError(
                f"findings[{i}] is missing keys: {missing}"
            )
        supporting = tuple(item.get("supporting_chunk_ids") or [])
        gaps.append(
            GapInput(
                cluster_id=int(item["cluster_id"]),
                cluster_size=int(item["cluster_size"]),
                gap_question=str(item["gap_question"]),
                suggested_note_title=str(item["suggested_note_title"]),
                rationale=str(item["rationale"]),
                supporting_chunk_ids=supporting,
            )
        )
    return gaps


# ─── step 4: retrieve_support ─────────────────────────────────────────────────


def retrieve_support(
    gap: GapInput,
    store: "VectorStore",
    embedder: "Embedder",
    *,
    top_k: int = 8,
    mode: "Mode" = "rerank",
    reranker: "Reranker | None" = None,
) -> list[SupportingChunk]:
    """Retrieve evidence chunks for one gap, merging with the gap's own hints.

    Two-stage retrieval:
    1. Query the store using the gap question as the search string.
    2. Union the query results with ``gap.supporting_chunk_ids`` (from the
       gap generator) — the generator already knows which chunks imply the
       gap, so they should always appear in the evidence set.

    After dedup by chunk_id, the list is sorted by retrieval rank (best
    first). ``top_k`` caps the final set **after** the union so the
    drafter sees at most ``top_k`` chunks.
    """
    from wikilens.query import query

    results = query(
        gap.gap_question,
        store=store,
        embedder=embedder,
        mode=mode,
        k=top_k,
        reranker=reranker,
    )

    # Build a dict keyed by chunk_id so union dedup is O(n).
    by_id: dict[str, SupportingChunk] = {}
    for r in results:
        by_id[r.chunk_id] = SupportingChunk(
            chunk_id=r.chunk_id,
            source_rel=r.source_rel,
            heading_path=r.heading_path,
            text=r.text,
            retrieval_rank=r.rank,
            retrieval_score=r.score,
        )

    # Union with the gap's pre-identified supporting chunk IDs.
    # These were surfaced during clustering (P5) and may not appear in the
    # top-k query results (e.g., if the query is lexically unusual).
    if gap.supporting_chunk_ids:
        # Pull those chunks from the store if not already in by_id.
        missing_ids = set(gap.supporting_chunk_ids) - by_id.keys()
        if missing_ids:
            all_rows = store._get_or_create_table().to_arrow().to_pylist()  # type: ignore[attr-defined]
            rank_offset = len(by_id) + 1
            for row in all_rows:
                cid = row.get("chunk_id", "")
                if cid in missing_ids:
                    by_id[cid] = SupportingChunk(
                        chunk_id=cid,
                        source_rel=row.get("source_rel", ""),
                        heading_path=tuple(row.get("heading_path") or []),
                        text=row.get("text", ""),
                        retrieval_rank=rank_offset,
                        retrieval_score=0.0,
                    )
                    rank_offset += 1

    # Sort by rank, cap at top_k.
    chunks = sorted(by_id.values(), key=lambda c: c.retrieval_rank)
    return chunks[:top_k]


# ─── step 7: check_attribution ────────────────────────────────────────────────

# Sentence-ending pattern: period / ? / ! followed by space or end-of-string,
# but not inside a code span or footnote definition line.
_FOOTNOTE_REF_RE = re.compile(r"\[\^(\d+)\]")
_FOOTNOTE_DEF_RE = re.compile(r"^\[\^(\d+)\]:\s*`([^`]+)`", re.MULTILINE)


def _extract_what_vault_says(body: str) -> str:
    """Return the text of the '## What the vault says' section only."""
    match = re.search(
        r"##\s+What the vault says\s*\n(.*?)(?=\n##\s|\Z)",
        body,
        re.DOTALL,
    )
    if not match:
        return ""
    return match.group(1).strip()


def _parse_citations_section(body: str) -> dict[int, str]:
    """Return {footnote_id: chunk_id} from the Citations section."""
    return {int(m.group(1)): m.group(2) for m in _FOOTNOTE_DEF_RE.finditer(body)}


def check_attribution(
    body_markdown: str,
    retrieved_chunk_ids: set[str],
) -> tuple[AttributionReport, tuple[Citation, ...]]:
    """Parse citations from a drafted body and check structural compliance.

    Returns:
        ``(AttributionReport, citations)`` where ``citations`` are the
        ``Citation`` records parsed from the "Citations" section.

    Checks:
    1. Every ``[^N]`` in "What the vault says" resolves to a definition in
       "Citations" (no orphan footnote references).
    2. Every definition's ``chunk_id`` is in ``retrieved_chunk_ids`` (no
       citation to a chunk that wasn't in the evidence set).
    3. ``attribution_rate`` = sentences-with-at-least-one-citation /
       total-declarative-sentences.

    Skips footnote check for external-research stubs (identified by the
    absence of any ``[^N]`` refs in the whole body).
    """
    vault_section = _extract_what_vault_says(body_markdown)
    fn_defs = _parse_citations_section(body_markdown)

    # Build Citation records.
    citations: list[Citation] = []
    for fn_id, chunk_id in fn_defs.items():
        # Find snippet from citations section text.
        snip_match = re.search(
            rf"^\[\^{fn_id}\]:\s*`[^`]+`\s*[—–-]\s*\"([^\"]+)\"",
            body_markdown,
            re.MULTILINE,
        )
        snippet = snip_match.group(1) if snip_match else ""
        citations.append(Citation(footnote_id=fn_id, chunk_id=chunk_id, snippet=snippet))

    # If no citations defined at all → external-research stub → vacuously OK.
    if not fn_defs and not _FOOTNOTE_REF_RE.search(body_markdown):
        return (
            AttributionReport(total_sentences=0, cited_sentences=0),
            tuple(citations),
        )

    # Strategy: scan the vault section line-by-line (not sentence-by-sentence).
    # Each non-blank, non-footnote-definition line counts as one sentence unit.
    # A line is "cited" if it contains at least one [^N] reference.
    # This is more robust than regex sentence splitting across inline refs.
    lines = vault_section.splitlines()
    sentences: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("[^"):
            continue
        sentences.append(stripped)

    total_sentences = len(sentences)
    cited_sentences = sum(
        1 for s in sentences if _FOOTNOTE_REF_RE.search(s)
    )

    # Orphan references: [^N] in vault section with no matching definition.
    used_fn_ids = {
        int(m.group(1))
        for m in _FOOTNOTE_REF_RE.finditer(vault_section)
    }
    orphan_footnotes = tuple(sorted(used_fn_ids - fn_defs.keys()))

    # Invalid chunk refs: defined footnotes whose chunk_id isn't in retrieved set.
    invalid_chunk_refs = tuple(
        sorted(
            chunk_id
            for chunk_id in fn_defs.values()
            if chunk_id not in retrieved_chunk_ids
        )
    )

    report = AttributionReport(
        total_sentences=total_sentences,
        cited_sentences=cited_sentences,
        orphan_footnotes=orphan_footnotes,
        invalid_chunk_refs=invalid_chunk_refs,
    )
    return report, tuple(citations)


# ─── step 5: draft_answers pipeline ──────────────────────────────────────────


def draft_answers(
    gaps: list[GapInput],
    store: "VectorStore",
    embedder: "Embedder",
    drafter: "Drafter",
    *,
    top_k: int = 8,
    mode: "Mode" = "rerank",
    reranker: "Reranker | None" = None,
    min_supporting: int = 2,
    sample: int | None = None,
    drafter_model: str = "",
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
    """
    from wikilens.drafter import DraftInput

    to_process = gaps if sample is None else gaps[:sample]
    drafts: list[AnswerDraft] = []

    for gap in to_process:
        chunks = retrieve_support(
            gap,
            store,
            embedder,
            top_k=top_k,
            mode=mode,
            reranker=reranker,
        )

        if len(chunks) < min_supporting:
            # Not enough evidence — emit external-research stub.
            draft_input = DraftInput(
                gap_question=gap.gap_question,
                suggested_note_title=gap.suggested_note_title,
                rationale=gap.rationale,
                chunks=tuple(
                    (c.chunk_id, c.source_rel, c.text) for c in chunks
                ),
                is_external_research=True,
            )
            body = drafter.draft_stub(draft_input)
            retrieved_ids = {c.chunk_id for c in chunks}
            attr_report, citations = check_attribution(body, retrieved_ids)
            drafts.append(
                AnswerDraft(
                    gap=gap,
                    supporting_chunks=tuple(chunks),
                    evidence_strength="external-research",
                    body_markdown=body,
                    citations=citations,
                    attribution=attr_report,
                    drafter_name=drafter.name,
                    model=drafter_model,
                )
            )
            continue

        draft_input = DraftInput(
            gap_question=gap.gap_question,
            suggested_note_title=gap.suggested_note_title,
            rationale=gap.rationale,
            chunks=tuple(
                (c.chunk_id, c.source_rel, c.text) for c in chunks
            ),
            is_external_research=False,
        )
        body = drafter.draft_stub(draft_input)
        retrieved_ids = {c.chunk_id for c in chunks}
        attr_report, citations = check_attribution(body, retrieved_ids)

        # Classify evidence_strength: "thin" when attribution is structurally
        # unclean or the attribution rate is below the §D5 threshold.
        if not attr_report.is_clean or attr_report.attribution_rate < 0.5:
            strength: EvidenceStrength = "thin"
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
