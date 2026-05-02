"""Output formatters for `wikilens answer` (P6).

Mirrors ``audit_format.py`` / ``gap_format.py``:
- ``render_stub`` produces the full on-disk Markdown file (YAML frontmatter +
  body) for one draft.
- ``format_markdown`` concatenates all stubs for stdout output.
- ``format_json`` emits a structured run report.
- ``write_stubs`` materialises one ``.md`` file per non-skipped draft under an
  output directory (``--write --out DIR``).

The JSON schema version is part of the public interface — bump on breaking
changes.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from wikilens.answer import AnswerDraft, AnswerReport

JSON_SCHEMA_VERSION = 1


# ─── helpers ──────────────────────────────────────────────────────────────────


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _wikilinks_from_draft(draft: AnswerDraft) -> list[str]:
    """Unique sorted wikilinks derived from cited supporting chunks.

    Only chunks that appear in at least one footnote citation are included —
    we don't add wikilinks for unreferenced retrieval results. Basename
    is the ``source_rel`` stem without extension (Obsidian convention).
    """
    cited_chunk_ids = {c.chunk_id for c in draft.citations}
    basenames: set[str] = set()
    for chunk in draft.supporting_chunks:
        if chunk.chunk_id in cited_chunk_ids:
            basenames.add(Path(chunk.source_rel).stem)
    return sorted(basenames)


def _inject_related_notes(body: str, wikilinks: list[str]) -> str:
    """Replace the '## Related notes' section content with populated wikilinks.

    The drafter is instructed to leave this section empty; the pipeline
    fills it here from the verified citation set (D10). The model sometimes
    writes filler text ("EMPTY", "_none_", etc.) — we replace whatever
    is between the header and the next ## section (or end-of-string).
    """
    if not wikilinks:
        return body
    wikilink_block = "\n".join(f"- [[{wl}]]" for wl in wikilinks)
    # Match: the header line, any blank/filler lines, stopping before the
    # next ## header.  We use a two-group capture so the replacement can
    # reattach the next-section separator correctly.
    return re.sub(
        r"(## Related notes\n)(?:.*?)(\n##\s)",
        rf"\g<1>\n{wikilink_block}\n\g<2>",
        body,
        count=1,
        flags=re.DOTALL,
    )


# ─── render_stub ──────────────────────────────────────────────────────────────


def render_stub(draft: AnswerDraft, *, generated_at: str | None = None) -> str:
    """Render a single complete Markdown stub file (frontmatter + body).

    Returns the full file content as a string — the caller decides whether
    to print it or write it to disk.
    """
    ts = generated_at or _now_iso()
    wikilinks = _wikilinks_from_draft(draft)
    body = _inject_related_notes(draft.body_markdown, wikilinks)

    chunk_ids_yaml = (
        "\n".join(f"  - {c.chunk_id}" for c in draft.supporting_chunks)
        if draft.supporting_chunks
        else "  []"
    )
    # Avoid trailing whitespace on empty model field.
    model_line = f"generator: {draft.drafter_name}/{draft.model}" if draft.model else f"generator: {draft.drafter_name}"

    frontmatter = f"""\
---
title: {draft.gap.suggested_note_title}
generated_by: wikilens-answer
generated_at: {ts}
source_gap_question: "{draft.gap.gap_question.replace('"', "'")}"
source_cluster_id: {draft.gap.cluster_id}
{model_line}
evidence_strength: {draft.evidence_strength}
supporting_chunks:
{chunk_ids_yaml}
---
"""

    heading = f"# {draft.gap.suggested_note_title.replace('-', ' ').title()}\n"
    gap_callout = f"\n> **Gap:** {draft.gap.gap_question}\n"

    return frontmatter + "\n" + heading + gap_callout + "\n" + body


# ─── format_markdown ──────────────────────────────────────────────────────────


def format_markdown(report: AnswerReport, *, generated_at: str | None = None) -> str:
    """Render all non-skipped drafts separated by horizontal rules.

    Summary header first, then one stub section per gap.
    """
    ts = generated_at or _now_iso()
    lines: list[str] = []
    lines.append(f"# Answer report — {report.vault_root}")
    lines.append("")
    lines.append(
        f"Gaps loaded from `{report.gaps_path}`. "
        f"Drafter: {report.drafter_name}/{report.model} "
        f"({report.retrieval_mode} retrieval, top-{report.top_k}). "
        f"Generated at {ts}."
    )
    lines.append("")
    lines.append(
        f"**{report.total_drafted}** drafted, "
        f"**{report.total_external_research}** external-research, "
        f"**{report.total_skipped}** skipped."
    )
    lines.append("")

    for draft in report.drafts:
        lines.append("---")
        lines.append("")
        if draft.skipped:
            lines.append(
                f"### {draft.gap.suggested_note_title} — *skipped* "
                f"({draft.skip_reason})"
            )
            lines.append("")
            continue
        lines.append(render_stub(draft, generated_at=ts))
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


# ─── format_json ──────────────────────────────────────────────────────────────


def format_json(report: AnswerReport, *, generated_at: str | None = None) -> str:
    """Stable JSON report. Sorted keys for clean diffs."""
    ts = generated_at or _now_iso()

    drafts_out: list[dict] = []
    for d in report.drafts:
        drafts_out.append(
            {
                "gap_id": d.gap.suggested_note_title,
                "gap_question": d.gap.gap_question,
                "cluster_id": d.gap.cluster_id,
                "evidence_strength": d.evidence_strength,
                "skipped": d.skipped,
                "skip_reason": d.skip_reason,
                "drafter": d.drafter_name,
                "model": d.model,
                "attribution": {
                    "total_sentences": d.attribution.total_sentences,
                    "cited_sentences": d.attribution.cited_sentences,
                    "attribution_rate": round(d.attribution.attribution_rate, 4),
                    "is_clean": d.attribution.is_clean,
                    "orphan_footnotes": list(d.attribution.orphan_footnotes),
                    "invalid_chunk_refs": list(d.attribution.invalid_chunk_refs),
                },
                "supporting_chunks": [
                    {
                        "chunk_id": c.chunk_id,
                        "source_rel": c.source_rel,
                        "retrieval_rank": c.retrieval_rank,
                        "retrieval_score": round(c.retrieval_score, 4),
                    }
                    for c in d.supporting_chunks
                ],
                "body_markdown": d.body_markdown if not d.skipped else "",
            }
        )

    doc: dict = {
        "schema_version": JSON_SCHEMA_VERSION,
        "generated_at": ts,
        "vault_root": report.vault_root,
        "gaps_path": report.gaps_path,
        "drafter": report.drafter_name,
        "model": report.model,
        "retrieval_mode": report.retrieval_mode,
        "top_k": report.top_k,
        "min_supporting": report.min_supporting,
        "stats": {
            "total_gaps": report.total_drafts,
            "drafted": report.total_drafted,
            "external_research": report.total_external_research,
            "skipped": report.total_skipped,
        },
        "drafts": drafts_out,
    }
    return json.dumps(doc, indent=2, sort_keys=True) + "\n"


# ─── write_stubs ──────────────────────────────────────────────────────────────


class CollisionError(Exception):
    """Raised when ``write_stubs`` finds existing files and ``--force`` is not set."""

    def __init__(self, collisions: list[Path]):
        self.collisions = collisions
        paths = ", ".join(str(p) for p in collisions)
        super().__init__(
            f"Cannot write stubs — {len(collisions)} file(s) already exist: {paths}. "
            "Move or rename them before re-running."
        )


class UnsafeStubTitleError(ValueError):
    """Raised when a generated note title cannot be safely used as a filename."""


_UNSAFE_PATH_CHARS_RE = re.compile(r"[\\/:\0]")
_SLUG_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_stub_filename(title: str) -> str:
    raw = title.strip()
    if not raw or raw in {".", ".."}:
        raise UnsafeStubTitleError(f"unsafe stub title: {title!r}")
    if _UNSAFE_PATH_CHARS_RE.search(raw):
        raise UnsafeStubTitleError(f"unsafe stub title: {title!r}")

    slug = _SLUG_RE.sub("-", raw).strip("._-").lower()
    if not slug or slug in {".", ".."}:
        raise UnsafeStubTitleError(f"unsafe stub title: {title!r}")
    return f"{slug}.md"


def _stub_target(out_dir: Path, title: str) -> Path:
    root = out_dir.resolve()
    target = (root / _safe_stub_filename(title)).resolve()
    if not target.is_relative_to(root):
        raise UnsafeStubTitleError(f"unsafe stub title: {title!r}")
    return target


def write_stubs(
    report: AnswerReport,
    out_dir: Path,
    *,
    generated_at: str | None = None,
) -> list[Path]:
    """Write one ``.md`` file per non-skipped draft to ``out_dir``.

    Returns the list of files written.

    Raises ``CollisionError`` if any target file already exists — no files
    are written in that case (check-then-create, not create-then-check). The
    caller owns the decision to delete or rename collisions; this function
    never silently overwrites.

    ``out_dir`` is created if it doesn't exist.
    """
    ts = generated_at or _now_iso()
    out_dir.mkdir(parents=True, exist_ok=True)

    to_write = [d for d in report.drafts if not d.skipped]

    # Resolve safe targets first — raises UnsafeStubTitleError before any I/O.
    targets = [(d, _stub_target(out_dir, d.gap.suggested_note_title)) for d in to_write]

    # Collision check — all-or-nothing write.
    collisions = [target for _draft, target in targets if target.exists()]
    if collisions:
        raise CollisionError(collisions)

    written: list[Path] = []
    for draft, target in targets:
        content = render_stub(draft, generated_at=ts)
        target.write_text(content, encoding="utf-8")
        written.append(target)

    return written
