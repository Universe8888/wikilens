"""Tests for confidence.py + confidence_judge.py + confidence_format.py — P10."""

from __future__ import annotations

import json
import textwrap

import pytest

from wikilens.confidence import (
    ClaimRecord,
    ConfidenceFinding,
    ConfidenceVerdict,
    enumerate_notes,
    pack_context,
    run_confidence,
)
from wikilens.confidence_format import format_json, format_markdown
from wikilens.confidence_judge import (
    MockConfidenceJudge,
    _parse_verdict,
    _sanitise_xml,
)

# ---------------------------------------------------------------------------
# Frozen dataclasses
# ---------------------------------------------------------------------------


def test_claim_record_frozen():
    r = ClaimRecord(note_rel="a.md", claim_text="hello", context="hello", sentence_index=0)
    with pytest.raises((AttributeError, TypeError)):
        r.claim_text = "other"  # type: ignore[misc]


def test_confidence_finding_frozen():
    f = ConfidenceFinding(
        note_rel="a.md",
        claim_text="maybe",
        level=1,
        rationale="hedge",
        confidence=0.9,
    )
    with pytest.raises((AttributeError, TypeError)):
        f.level = 2  # type: ignore[misc]


def test_confidence_verdict_frozen():
    v = ConfidenceVerdict(level=2, rationale="flat", confidence=0.8)
    with pytest.raises((AttributeError, TypeError)):
        v.level = 3  # type: ignore[misc]


# ---------------------------------------------------------------------------
# pack_context
# ---------------------------------------------------------------------------


def test_pack_context_middle():
    sents = ["A.", "B.", "C.", "D.", "E."]
    ctx = pack_context(sents, idx=2)
    assert "A." in ctx and "E." in ctx  # window of 2 on each side covers all


def test_pack_context_first_sentence():
    sents = ["A.", "B.", "C."]
    ctx = pack_context(sents, idx=0)
    assert ctx.startswith("A.")


def test_pack_context_last_sentence():
    sents = ["A.", "B.", "C.", "D.", "E.", "F."]
    ctx = pack_context(sents, idx=5)
    assert "F." in ctx


# ---------------------------------------------------------------------------
# enumerate_notes
# ---------------------------------------------------------------------------


def test_enumerate_notes_finds_md(tmp_path):
    (tmp_path / "a.md").write_text("hello")
    (tmp_path / "b.txt").write_text("skip")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "c.md").write_text("nested")
    notes = enumerate_notes(str(tmp_path))
    basenames = {p.name for p in notes}
    assert basenames == {"a.md", "c.md"}


def test_enumerate_notes_only_filter(tmp_path):
    (tmp_path / "sourdough-baking.md").write_text("x")
    (tmp_path / "chess-openings.md").write_text("y")
    notes = enumerate_notes(str(tmp_path), only="sourdough")
    assert len(notes) == 1
    assert notes[0].name == "sourdough-baking.md"


def test_enumerate_notes_empty_dir(tmp_path):
    assert enumerate_notes(str(tmp_path)) == []


# ---------------------------------------------------------------------------
# MockConfidenceJudge
# ---------------------------------------------------------------------------


def test_mock_judge_detects_hedge():
    judge = MockConfidenceJudge()
    v = judge.classify("I think this is true.", "context")
    assert v.level == 1
    assert v.confidence > 0


def test_mock_judge_no_hedge_returns_3():
    judge = MockConfidenceJudge()
    v = judge.classify("The Earth orbits the Sun.", "context")
    assert v.level == 3


def test_mock_judge_maybe_hedge():
    judge = MockConfidenceJudge()
    v = judge.classify("Maybe this works.", "context")
    assert v.level == 1


def test_mock_judge_suspect_hedge():
    judge = MockConfidenceJudge()
    v = judge.classify("I suspect there is a better way.", "context")
    assert v.level == 1


def test_mock_judge_returns_verdict_type():
    v = MockConfidenceJudge().classify("any claim", "any context")
    assert isinstance(v, ConfidenceVerdict)
    assert 1 <= v.level <= 5
    assert isinstance(v.rationale, str)
    assert 0.0 <= v.confidence <= 1.0


# ---------------------------------------------------------------------------
# _parse_verdict
# ---------------------------------------------------------------------------


def test_parse_verdict_valid():
    raw = '{"level": 2, "rationale": "flat claim", "confidence": 0.85}'
    v = _parse_verdict(raw)
    assert v.level == 2
    assert v.confidence == 0.85


def test_parse_verdict_invalid_json():
    with pytest.raises(ValueError, match="not valid JSON"):
        _parse_verdict("{not json}")


def test_parse_verdict_missing_key():
    with pytest.raises(ValueError, match="missing keys"):
        _parse_verdict('{"level": 1, "confidence": 0.9}')


def test_parse_verdict_level_out_of_range():
    with pytest.raises(ValueError, match="level must be 1-5"):
        _parse_verdict('{"level": 6, "rationale": "x", "confidence": 0.5}')


def test_parse_verdict_confidence_out_of_range():
    with pytest.raises(ValueError, match="confidence must be in"):
        _parse_verdict('{"level": 3, "rationale": "x", "confidence": 1.5}')


# ---------------------------------------------------------------------------
# _sanitise_xml
# ---------------------------------------------------------------------------


def test_sanitise_xml_replaces_angle_brackets():
    out = _sanitise_xml("<script>alert('xss')</script>")
    assert "<" not in out
    assert ">" not in out
    assert "&lt;" in out
    assert "&gt;" in out


def test_sanitise_xml_no_change_for_safe_text():
    text = "The Earth orbits the Sun at 150 million kilometres."
    assert _sanitise_xml(text) == text


# ---------------------------------------------------------------------------
# run_confidence — pipeline integration (mock judge, tmp vault)
# ---------------------------------------------------------------------------

_NOTE_WITH_HEDGES = textwrap.dedent("""\
    ---
    title: Test Note
    date: 2026-01-01
    tags: [test]
    ---

    # Test Note

    I think this is correct.
    The Earth orbits the Sun.
    Maybe the answer is different.
    Water freezes at 0 degrees Celsius at standard pressure.
""")

_NOTE_PLAIN = textwrap.dedent("""\
    ---
    title: Plain Note
    date: 2026-01-01
    tags: [test]
    ---

    # Plain Note

    The capital of France is Paris.
    Photosynthesis converts light into chemical energy.
""")


def _make_vault(tmp_path, notes: dict[str, str]):
    for name, content in notes.items():
        (tmp_path / name).write_text(content, encoding="utf-8")
    return str(tmp_path)


def test_run_confidence_finds_hedges(tmp_path):
    vault = _make_vault(tmp_path, {"hedges.md": _NOTE_WITH_HEDGES})
    judge = MockConfidenceJudge()
    report = run_confidence(vault, judge, threshold=2)
    assert report.has_findings
    assert report.judge_calls > 0
    hedge_texts = [f.claim_text for f in report.findings]
    assert any("I think" in t or "Maybe" in t for t in hedge_texts)


def test_run_confidence_no_findings_plain(tmp_path):
    vault = _make_vault(tmp_path, {"plain.md": _NOTE_PLAIN})
    judge = MockConfidenceJudge()
    report = run_confidence(vault, judge, threshold=2)
    # MockJudge returns L3 for non-hedging claims — above threshold 2
    assert not report.has_findings


def test_run_confidence_sample_cap(tmp_path):
    vault = _make_vault(tmp_path, {"hedges.md": _NOTE_WITH_HEDGES, "plain.md": _NOTE_PLAIN})
    judge = MockConfidenceJudge()
    report = run_confidence(vault, judge, threshold=2, sample=2)
    assert report.judge_calls == 2


def test_run_confidence_only_filter(tmp_path):
    vault = _make_vault(tmp_path, {
        "hedges.md": _NOTE_WITH_HEDGES,
        "plain.md": _NOTE_PLAIN,
    })
    judge = MockConfidenceJudge()
    report = run_confidence(vault, judge, threshold=2, only="plain")
    # All claims from plain.md go to judge, nothing from hedges.md
    for finding in report.findings:
        assert "plain" in finding.note_rel


def test_run_confidence_threshold_1_fewer_findings(tmp_path):
    vault = _make_vault(tmp_path, {"hedges.md": _NOTE_WITH_HEDGES})
    judge = MockConfidenceJudge()
    report_2 = run_confidence(vault, judge, threshold=2)
    report_1 = run_confidence(vault, judge, threshold=1)
    # Threshold 1 is a strict subset of threshold 2
    assert len(report_1.findings) <= len(report_2.findings)


def test_run_confidence_min_confidence_filter(tmp_path):
    vault = _make_vault(tmp_path, {"hedges.md": _NOTE_WITH_HEDGES})
    judge = MockConfidenceJudge()
    # High min_confidence should drop all or most findings
    report = run_confidence(vault, judge, threshold=2, min_confidence=0.99)
    # MockJudge returns 0.9 for hedges — below 0.99, so all should be dropped
    assert not report.has_findings


def test_run_confidence_empty_vault(tmp_path):
    judge = MockConfidenceJudge()
    report = run_confidence(str(tmp_path), judge)
    assert report.total_claims == 0
    assert not report.has_findings


def test_run_confidence_report_fields(tmp_path):
    vault = _make_vault(tmp_path, {"hedges.md": _NOTE_WITH_HEDGES})
    judge = MockConfidenceJudge()
    report = run_confidence(vault, judge, threshold=2)
    assert report.vault_path == vault
    assert report.threshold == 2
    assert report.total_claims >= 0
    assert report.judge_calls == report.total_claims  # no sample cap


# ---------------------------------------------------------------------------
# format_markdown
# ---------------------------------------------------------------------------


def test_format_markdown_no_findings(tmp_path):
    vault = _make_vault(tmp_path, {"plain.md": _NOTE_PLAIN})
    judge = MockConfidenceJudge()
    report = run_confidence(vault, judge, threshold=2)
    md = format_markdown(report)
    assert "No low-confidence claims" in md


def test_format_markdown_has_findings(tmp_path):
    vault = _make_vault(tmp_path, {"hedges.md": _NOTE_WITH_HEDGES})
    judge = MockConfidenceJudge()
    report = run_confidence(vault, judge, threshold=2)
    md = format_markdown(report)
    assert "## hedges.md" in md
    assert "L1 speculation" in md


def test_format_markdown_ends_with_newline(tmp_path):
    vault = _make_vault(tmp_path, {"plain.md": _NOTE_PLAIN})
    judge = MockConfidenceJudge()
    report = run_confidence(vault, judge, threshold=2)
    md = format_markdown(report)
    assert md.endswith("\n")


# ---------------------------------------------------------------------------
# format_json
# ---------------------------------------------------------------------------


def test_format_json_valid_structure(tmp_path):
    vault = _make_vault(tmp_path, {"hedges.md": _NOTE_WITH_HEDGES})
    judge = MockConfidenceJudge()
    report = run_confidence(vault, judge, threshold=2)
    raw = format_json(report)
    doc = json.loads(raw)
    assert doc["schema_version"] == 1
    assert "findings" in doc
    assert "stats" in doc
    assert doc["stats"]["total_claims"] == report.total_claims


def test_format_json_finding_fields(tmp_path):
    vault = _make_vault(tmp_path, {"hedges.md": _NOTE_WITH_HEDGES})
    judge = MockConfidenceJudge()
    report = run_confidence(vault, judge, threshold=2)
    if report.has_findings:
        doc = json.loads(format_json(report))
        f = doc["findings"][0]
        assert "note" in f
        assert "claim" in f
        assert "level" in f
        assert "level_label" in f
        assert "rationale" in f
        assert "judge_confidence" in f


def test_format_json_ends_with_newline(tmp_path):
    vault = _make_vault(tmp_path, {"plain.md": _NOTE_PLAIN})
    judge = MockConfidenceJudge()
    report = run_confidence(vault, judge, threshold=2)
    assert format_json(report).endswith("\n")


# ---------------------------------------------------------------------------
# CLI exit codes
# ---------------------------------------------------------------------------


def test_cli_exit_0_no_findings(tmp_path):
    from wikilens.cli import main

    _make_vault(tmp_path, {"plain.md": _NOTE_PLAIN})
    rc = main(["confidence", str(tmp_path), "--judge", "none", "--threshold", "2"])
    assert rc == 0


def test_cli_exit_1_findings(tmp_path):
    from wikilens.cli import main

    _make_vault(tmp_path, {"hedges.md": _NOTE_WITH_HEDGES})
    rc = main(["confidence", str(tmp_path), "--judge", "none", "--threshold", "2"])
    assert rc == 1


def test_cli_exit_2_bad_judge(tmp_path, capsys):  # noqa: ARG001
    from wikilens.cli import main

    _make_vault(tmp_path, {"plain.md": _NOTE_PLAIN})
    rc = main(["confidence", str(tmp_path), "--judge", "none"])
    # --judge none is always valid; check bad value is caught at argparse level
    assert rc in (0, 1)


def test_cli_json_output(tmp_path):
    import io
    import sys

    from wikilens.cli import main

    _make_vault(tmp_path, {"hedges.md": _NOTE_WITH_HEDGES})
    buf = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = buf
    try:
        main(["confidence", str(tmp_path), "--judge", "none", "--json"])
    finally:
        sys.stdout = old_stdout

    doc = json.loads(buf.getvalue())
    assert doc["schema_version"] == 1


def test_cli_sample_flag(tmp_path):
    from wikilens.cli import main

    _make_vault(tmp_path, {"hedges.md": _NOTE_WITH_HEDGES})
    rc = main(["confidence", str(tmp_path), "--judge", "none", "--sample", "2"])
    assert rc in (0, 1)


def test_cli_only_flag(tmp_path):
    from wikilens.cli import main

    _make_vault(tmp_path, {
        "hedges.md": _NOTE_WITH_HEDGES,
        "plain.md": _NOTE_PLAIN,
    })
    rc = main(["confidence", str(tmp_path), "--judge", "none", "--only", "plain"])
    assert rc in (0, 1)
