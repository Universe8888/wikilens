"""Tests for answer_format.py — stub renderer, JSON schema, file-write policy."""

from __future__ import annotations

from pathlib import Path

import pytest

from wikilens.answer import (
    AnswerDraft,
    AnswerReport,
    AttributionReport,
    Citation,
    GapInput,
    SupportingChunk,
)
from wikilens.answer_format import (
    JSON_SCHEMA_VERSION,
    CollisionError,
    format_json,
    format_markdown,
    render_stub,
    write_stubs,
)

_FIXED_TS = "2026-05-01T12:00:00Z"

_BODY = """\
## What the vault says

Light reactions produce ATP and NADPH.[^1]

## Evidence gaps

- The Calvin cycle mechanism is not covered.

## Related notes

## Citations

[^1]: `c1` — "Light reactions produce ATP..."
"""


def _mk_gap(title: str = "calvin-cycle") -> GapInput:
    return GapInput(
        cluster_id=3,
        cluster_size=5,
        gap_question="What is the Calvin cycle?",
        suggested_note_title=title,
        rationale="notes describe light reactions but not dark reactions",
        supporting_chunk_ids=("c1",),
    )


def _mk_chunk(chunk_id: str = "c1", source_rel: str = "photosynthesis.md") -> SupportingChunk:
    return SupportingChunk(
        chunk_id=chunk_id,
        source_rel=source_rel,
        heading_path=("Light reactions",),
        text="Light reactions produce ATP and NADPH.",
        retrieval_rank=1,
        retrieval_score=0.9,
    )


def _mk_draft(
    title: str = "calvin-cycle",
    skipped: bool = False,
    strength: str = "strong",
    body: str = _BODY,
) -> AnswerDraft:
    chunk = _mk_chunk()
    citation = Citation(footnote_id=1, chunk_id="c1", snippet="Light reactions produce ATP...")
    return AnswerDraft(
        gap=_mk_gap(title),
        supporting_chunks=(chunk,),
        evidence_strength=strength,  # type: ignore[arg-type]
        body_markdown=body,
        citations=(citation,),
        attribution=AttributionReport(total_sentences=1, cited_sentences=1),
        drafter_name="mock",
        model="mock",
        skipped=skipped,
        skip_reason="min-supporting not met" if skipped else "",
    )


def _mk_report(*drafts: AnswerDraft) -> AnswerReport:
    return AnswerReport(
        vault_root="fixtures/gaps_vault",
        gaps_path="gaps.json",
        drafter_name="mock",
        model="mock",
        retrieval_mode="hybrid",
        top_k=5,
        min_supporting=2,
        drafts=drafts,
    )


# ─── render_stub ──────────────────────────────────────────────────────────────


def test_render_stub_has_frontmatter():
    draft = _mk_draft()
    rendered = render_stub(draft, generated_at=_FIXED_TS)
    assert rendered.startswith("---\n")
    assert "generated_by: wikilens-answer" in rendered
    assert f"generated_at: {_FIXED_TS}" in rendered
    assert "evidence_strength: strong" in rendered
    assert "title: calvin-cycle" in rendered


def test_render_stub_has_level_one_heading():
    draft = _mk_draft()
    rendered = render_stub(draft, generated_at=_FIXED_TS)
    assert "# Calvin Cycle\n" in rendered


def test_render_stub_has_gap_callout():
    draft = _mk_draft()
    rendered = render_stub(draft, generated_at=_FIXED_TS)
    assert "> **Gap:** What is the Calvin cycle?" in rendered


def test_render_stub_includes_body():
    draft = _mk_draft()
    rendered = render_stub(draft, generated_at=_FIXED_TS)
    assert "## What the vault says" in rendered
    assert "## Evidence gaps" in rendered
    assert "## Citations" in rendered


def test_render_stub_injects_wikilinks():
    draft = _mk_draft()
    rendered = render_stub(draft, generated_at=_FIXED_TS)
    assert "## Related notes" in rendered
    assert "[[photosynthesis]]" in rendered


def test_render_stub_no_wikilinks_when_no_citations():
    # draft with empty citations → no wikilinks injected
    chunk = _mk_chunk()
    draft = AnswerDraft(
        gap=_mk_gap(),
        supporting_chunks=(chunk,),
        evidence_strength="strong",
        body_markdown=_BODY,
        citations=(),  # no citations
        attribution=AttributionReport(total_sentences=1, cited_sentences=0),
        drafter_name="mock",
        model="mock",
    )
    rendered = render_stub(draft, generated_at=_FIXED_TS)
    assert "[[" not in rendered


# ─── format_markdown ──────────────────────────────────────────────────────────


def test_format_markdown_includes_summary():
    report = _mk_report(_mk_draft())
    out = format_markdown(report, generated_at=_FIXED_TS)
    assert "# Answer report" in out
    assert "1** drafted" in out


def test_format_markdown_skipped_gap_shows_skip_reason():
    report = _mk_report(_mk_draft(skipped=True))
    out = format_markdown(report, generated_at=_FIXED_TS)
    assert "skipped" in out
    assert "min-supporting not met" in out


def test_format_markdown_mixed_drafts():
    report = _mk_report(
        _mk_draft("gap-a"),
        _mk_draft("gap-b", skipped=True),
    )
    out = format_markdown(report, generated_at=_FIXED_TS)
    assert "gap-a" in out
    assert "gap-b" in out


# ─── format_json ──────────────────────────────────────────────────────────────


def test_format_json_schema_version():
    import json
    report = _mk_report(_mk_draft())
    doc = json.loads(format_json(report, generated_at=_FIXED_TS))
    assert doc["schema_version"] == JSON_SCHEMA_VERSION


def test_format_json_stats_match_report():
    import json
    report = _mk_report(_mk_draft("a"), _mk_draft("b", skipped=True))
    doc = json.loads(format_json(report, generated_at=_FIXED_TS))
    assert doc["stats"]["total_gaps"] == 2
    assert doc["stats"]["drafted"] == 1
    assert doc["stats"]["skipped"] == 1


def test_format_json_draft_has_attribution_block():
    import json
    report = _mk_report(_mk_draft())
    doc = json.loads(format_json(report, generated_at=_FIXED_TS))
    attr = doc["drafts"][0]["attribution"]
    assert "attribution_rate" in attr
    assert "is_clean" in attr


def test_format_json_ends_with_newline():
    report = _mk_report(_mk_draft())
    out = format_json(report, generated_at=_FIXED_TS)
    assert out.endswith("\n")


# ─── write_stubs ──────────────────────────────────────────────────────────────


def test_write_stubs_creates_files(tmp_path: Path):
    report = _mk_report(_mk_draft("calvin-cycle"), _mk_draft("wsgi-vs-asgi"))
    written = write_stubs(report, tmp_path, generated_at=_FIXED_TS)
    assert len(written) == 2
    assert (tmp_path / "calvin-cycle.md").exists()
    assert (tmp_path / "wsgi-vs-asgi.md").exists()


def test_write_stubs_creates_out_dir(tmp_path: Path):
    out = tmp_path / "new_dir" / "stubs"
    report = _mk_report(_mk_draft())
    write_stubs(report, out, generated_at=_FIXED_TS)
    assert out.is_dir()


def test_write_stubs_skips_skipped_drafts(tmp_path: Path):
    report = _mk_report(_mk_draft("a"), _mk_draft("b", skipped=True))
    written = write_stubs(report, tmp_path, generated_at=_FIXED_TS)
    assert len(written) == 1
    assert not (tmp_path / "b.md").exists()


def test_write_stubs_raises_collision_error(tmp_path: Path):
    (tmp_path / "calvin-cycle.md").write_text("existing content")
    report = _mk_report(_mk_draft("calvin-cycle"))
    with pytest.raises(CollisionError) as exc_info:
        write_stubs(report, tmp_path, generated_at=_FIXED_TS)
    assert len(exc_info.value.collisions) == 1


def test_write_stubs_no_partial_write_on_collision(tmp_path: Path):
    """All-or-nothing: if any target exists, nothing is written."""
    (tmp_path / "gap-b.md").write_text("existing")
    report = _mk_report(_mk_draft("gap-a"), _mk_draft("gap-b"))
    with pytest.raises(CollisionError):
        write_stubs(report, tmp_path, generated_at=_FIXED_TS)
    assert not (tmp_path / "gap-a.md").exists()


def test_write_stubs_content_is_valid_stub(tmp_path: Path):
    report = _mk_report(_mk_draft())
    write_stubs(report, tmp_path, generated_at=_FIXED_TS)
    content = (tmp_path / "calvin-cycle.md").read_text(encoding="utf-8")
    assert content.startswith("---\n")
    assert "generated_by: wikilens-answer" in content
    assert "## What the vault says" in content
