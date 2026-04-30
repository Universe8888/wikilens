"""Tests for the `wikilens audit` CLI subcommand (P3, phase 3.4).

Covers exit codes, markdown vs JSON output, --only filtering, and the
bad-input failure mode. Uses a tiny in-tmp_path vault to keep each test
fast — no model loading touches audit.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from wikilens.cli import main


def _write(root: Path, rel: str, body: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


def _build_fixture(tmp_path: Path) -> Path:
    # Smallest vault that exhibits broken, one-way, orphan at once.
    _write(tmp_path, "a.md", "[[b]] [[ghost]]")
    _write(tmp_path, "b.md", "no backlinks here")
    return tmp_path


def test_audit_clean_vault_exit_zero(tmp_path: Path, capsys: pytest.CaptureFixture):
    _write(tmp_path, "a.md", "[[b]]")
    _write(tmp_path, "b.md", "[[a]]")  # reciprocal; no orphans; nothing broken

    rc = main(["audit", str(tmp_path)])

    assert rc == 0
    out = capsys.readouterr().out
    assert "Broken links (0)" in out
    assert "One-way links (0)" in out
    assert "Orphan notes (0)" in out
    assert "_none found._" in out


def test_audit_with_findings_exits_one(tmp_path: Path, capsys: pytest.CaptureFixture):
    vault = _build_fixture(tmp_path)

    rc = main(["audit", str(vault)])

    assert rc == 1
    out = capsys.readouterr().out
    assert "Broken links (1)" in out
    assert "ghost" in out
    assert "One-way links (1)" in out
    assert "Orphan notes (1)" in out


def test_audit_json_output_is_parseable(tmp_path: Path, capsys: pytest.CaptureFixture):
    vault = _build_fixture(tmp_path)

    rc = main(["audit", str(vault), "--json"])

    assert rc == 1
    out = capsys.readouterr().out
    doc = json.loads(out)
    assert doc["schema_version"] == 1
    assert doc["node_count"] == 2
    assert doc["total_findings"] == 3
    # Must include all four class keys when --only isn't set.
    assert set(doc) >= {"broken", "one_way", "orphans", "shadowed"}
    assert len(doc["broken"]) == 1
    assert doc["broken"][0]["target_raw"] == "ghost"


def test_audit_only_filter_markdown(tmp_path: Path, capsys: pytest.CaptureFixture):
    vault = _build_fixture(tmp_path)

    rc = main(["audit", str(vault), "--only", "broken"])

    assert rc == 1
    out = capsys.readouterr().out
    assert "Broken links" in out
    assert "One-way links" not in out
    assert "Orphan notes" not in out
    assert "Shadowed links" not in out


def test_audit_only_filter_json_omits_other_classes(
    tmp_path: Path, capsys: pytest.CaptureFixture
):
    vault = _build_fixture(tmp_path)

    rc = main(["audit", str(vault), "--json", "--only", "broken,orphan"])

    assert rc == 1
    out = capsys.readouterr().out
    doc = json.loads(out)
    assert "broken" in doc
    assert "orphans" in doc
    assert "one_way" not in doc
    assert "shadowed" not in doc


def test_audit_rejects_unknown_class(tmp_path: Path, capsys: pytest.CaptureFixture):
    vault = _build_fixture(tmp_path)

    rc = main(["audit", str(vault), "--only", "typo"])

    assert rc == 2
    err = capsys.readouterr().err
    assert "typo" in err
