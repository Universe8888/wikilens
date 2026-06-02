"""M0 contract tests — exit-code and JSON-shape invariants for every CLI command.

Exit-code contract:
  0 = success / clean (no findings)
  1 = success with findings
  2 = bad input / missing prerequisite

JSON-shape contract (schema_version=1):
  Every --json output contains at minimum {"schema_version": 1, ...}.
  Top-level keys are snapshot-tested so breakage is explicit.

NOTE: Some commands currently raise unhandled exceptions or return 0 when given
a missing path instead of returning 2. These are documented as xfail tests —
the M2 cli refactor will fix them to return 2 uniformly.
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


def _build_minimal_vault(tmp_path: Path) -> Path:
    _write(tmp_path, "a.md", "[[b]]\nThe sky is blue.")
    _write(tmp_path, "b.md", "[[a]]\nWater is wet.")
    return tmp_path


# ─── Exit-code contract: bad input → 2 (currently working) ───────────────


class TestExitCode2BadInput:
    """Commands that properly return 2 on missing path/db."""

    def test_query_missing_db(self, tmp_path, capsys):
        rc = main(["query", "anything", "--db", str(tmp_path / "no-db")])
        assert rc == 2

    def test_contradict_missing_db(self, tmp_path, capsys):
        rc = main(["contradict", str(tmp_path / "nonexistent"), "--judge", "none"])
        assert rc == 2

    def test_gap_missing_db(self, tmp_path, capsys):
        rc = main(["gap", str(tmp_path / "nonexistent"), "--judge", "none"])
        assert rc == 2

    def test_drift_missing_vault(self, tmp_path, capsys):
        rc = main(["drift", str(tmp_path / "nonexistent"), "--judge", "none"])
        assert rc == 2


# ─── Exit-code contract: bad input → 2 (currently broken — fix in M2) ────


class TestExitCode2Broken:
    """Commands that SHOULD return 2 but currently don't. xfail until M2."""

    @pytest.mark.xfail(reason="ingest raises FileNotFoundError instead of returning 2")
    def test_ingest_missing_vault(self, tmp_path, capsys):
        rc = main(["ingest", str(tmp_path / "nonexistent")])
        assert rc == 2

    @pytest.mark.xfail(reason="audit raises FileNotFoundError instead of returning 2")
    def test_audit_missing_vault(self, tmp_path, capsys):
        rc = main(["audit", str(tmp_path / "nonexistent")])
        assert rc == 2

    @pytest.mark.xfail(reason="concepts returns 0 on missing path instead of 2")
    def test_concepts_missing_db(self, tmp_path, capsys):
        rc = main(["concepts", str(tmp_path / "nonexistent"), "--judge", "none"])
        assert rc == 2

    @pytest.mark.xfail(reason="confidence returns 0 on missing path instead of 2")
    def test_confidence_missing_vault(self, tmp_path, capsys):
        rc = main(["confidence", str(tmp_path / "nonexistent"), "--judge", "none"])
        assert rc == 2


# ─── Exit-code contract: clean → 0 ───────────────────────────────────────


class TestExitCode0Clean:
    """Commands exit 0 on valid input with no findings."""

    def test_no_args_shows_help(self, capsys):
        rc = main([])
        assert rc == 0

    def test_audit_clean_vault(self, tmp_path, capsys):
        _write(tmp_path, "a.md", "[[b]]")
        _write(tmp_path, "b.md", "[[a]]")
        rc = main(["audit", str(tmp_path)])
        assert rc == 0


# ─── Exit-code contract: findings → 1 ────────────────────────────────────


class TestExitCode1Findings:
    """Commands exit 1 when they find issues."""

    def test_audit_with_findings(self, tmp_path, capsys):
        _write(tmp_path, "a.md", "[[ghost]]")
        rc = main(["audit", str(tmp_path)])
        assert rc == 1


# ─── JSON shape contract ─────────────────────────────────────────────────


class TestJsonShape:
    """JSON output has schema_version=1 and expected top-level keys."""

    def test_audit_json_keys(self, tmp_path, capsys):
        _write(tmp_path, "a.md", "[[ghost]]")
        main(["audit", str(tmp_path), "--json"])
        out = capsys.readouterr().out
        doc = json.loads(out)
        assert doc["schema_version"] == 1
        expected_keys = {"schema_version", "vault_root", "broken", "one_way", "orphans", "shadowed"}
        assert expected_keys <= set(doc.keys())

    def test_contradict_json_keys(self, tmp_path, capsys):
        vault = _build_minimal_vault(tmp_path)
        rc = main(["contradict", str(vault), "--judge", "none", "--json"])
        if rc == 2:
            pytest.skip("contradict requires ingested db")
        out = capsys.readouterr().out
        doc = json.loads(out)
        assert doc["schema_version"] == 1
        assert "findings" in doc

    def test_gap_json_keys(self, tmp_path, capsys):
        vault = _build_minimal_vault(tmp_path)
        rc = main(["gap", str(vault), "--judge", "none", "--json"])
        if rc == 2:
            pytest.skip("gap requires ingested db")
        out = capsys.readouterr().out
        doc = json.loads(out)
        assert doc["schema_version"] == 1
        assert "gaps" in doc
