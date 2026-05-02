"""Tests for drift_format.py (P8.4)."""

from __future__ import annotations

import json

from wikilens.drift import DriftEvent, DriftReport, Revision
from wikilens.drift_format import (
    JSON_SCHEMA_VERSION,
    format_json,
    format_markdown,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REV_A = Revision(sha="aaa00001", timestamp=1_738_368_000, rel_path="notes/chem.md", content="")
_REV_B = Revision(sha="bbb00002", timestamp=1_743_552_000, rel_path="notes/chem.md", content="")

_EVENT = DriftEvent(
    note_rel="notes/chem.md",
    before=_REV_A,
    after=_REV_B,
    before_claim="Water boils at 100C at all altitudes.",
    after_claim="Water boils at 100C only at sea level; boiling point drops with altitude.",
    drift_type="reversal",
    score=5,
    reasoning="Original absolute claim replaced by a pressure-aware one.",
)


def _report_with_event() -> DriftReport:
    r = DriftReport(
        vault="fixtures/drift_vault",
        repo_root="/repo",
        walked_commits=10,
        pairs_considered=5,
        pairs_filtered=3,
        pairs_judged=2,
        findings=[_EVENT],
    )
    return r


def _empty_report() -> DriftReport:
    return DriftReport(
        vault="fixtures/drift_vault",
        repo_root="/repo",
        walked_commits=10,
        pairs_considered=3,
        pairs_filtered=3,
        pairs_judged=0,
        findings=[],
    )


# ---------------------------------------------------------------------------
# format_markdown
# ---------------------------------------------------------------------------


def test_markdown_contains_vault_header():
    md = format_markdown(_report_with_event())
    assert "# Temporal drift findings" in md
    assert "fixtures/drift_vault" in md


def test_markdown_lists_event_count():
    md = format_markdown(_report_with_event())
    assert "1 drift event" in md


def test_markdown_contains_note_section():
    md = format_markdown(_report_with_event())
    assert "## notes/chem.md" in md


def test_markdown_contains_before_and_after_claims():
    md = format_markdown(_report_with_event())
    assert "Water boils at 100C at all altitudes" in md
    assert "only at sea level" in md


def test_markdown_contains_drift_type_and_score():
    md = format_markdown(_report_with_event())
    assert "reversal" in md
    assert "score 5" in md


def test_markdown_contains_reasoning():
    md = format_markdown(_report_with_event())
    assert "pressure-aware" in md


def test_markdown_contains_sha_prefix():
    md = format_markdown(_report_with_event())
    assert "aaa00001" in md
    assert "bbb00002" in md


def test_markdown_empty_report_no_drift_message():
    md = format_markdown(_empty_report())
    assert "No drift detected" in md
    assert "10" in md  # walked_commits


def test_markdown_ends_with_newline():
    assert format_markdown(_report_with_event()).endswith("\n")
    assert format_markdown(_empty_report()).endswith("\n")


# ---------------------------------------------------------------------------
# format_json
# ---------------------------------------------------------------------------


def test_json_schema_version():
    doc = json.loads(format_json(_report_with_event()))
    assert doc["schema_version"] == JSON_SCHEMA_VERSION


def test_json_contains_vault_and_repo():
    doc = json.loads(format_json(_report_with_event()))
    assert doc["vault"] == "fixtures/drift_vault"
    assert doc["repo_root"] == "/repo"


def test_json_stats_correct():
    doc = json.loads(format_json(_report_with_event()))
    s = doc["stats"]
    assert s["walked_commits"] == 10
    assert s["pairs_considered"] == 5
    assert s["pairs_filtered"] == 3
    assert s["pairs_judged"] == 2
    assert s["findings"] == 1


def test_json_finding_fields():
    doc = json.loads(format_json(_report_with_event()))
    f = doc["findings"][0]
    assert f["note"] == "notes/chem.md"
    assert f["type"] == "reversal"
    assert f["score"] == 5
    assert "pressure-aware" in f["reasoning"]
    assert f["before"]["sha"] == "aaa00001"
    assert f["after"]["sha"] == "bbb00002"
    assert "Water boils at 100C at all altitudes" in f["before"]["claim"]
    assert "only at sea level" in f["after"]["claim"]


def test_json_finding_has_date_fields():
    doc = json.loads(format_json(_report_with_event()))
    f = doc["findings"][0]
    assert "date" in f["before"]
    assert "date" in f["after"]
    # Dates should be ISO YYYY-MM-DD strings.
    import re
    assert re.match(r"\d{4}-\d{2}-\d{2}", f["before"]["date"])


def test_json_empty_report_has_empty_findings():
    doc = json.loads(format_json(_empty_report()))
    assert doc["findings"] == []
    assert doc["stats"]["findings"] == 0


def test_json_sorted_keys():
    raw = format_json(_report_with_event())
    lines = raw.splitlines()
    # Top-level keys should appear in sorted order.
    top_keys = [ln.strip().split(":")[0].strip('"') for ln in lines if ln.startswith('  "')]
    assert top_keys == sorted(top_keys)


def test_json_ends_with_newline():
    assert format_json(_report_with_event()).endswith("\n")
