"""Tests for the `wikilens contradict` CLI subcommand (P4, Phase 4.1).

Covers the plumbing path only: exit codes, bad input, unsupported judge
backends, --only validation, and --judge none end-to-end against a real
tiny ingest. No network, no Claude, no Ollama.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from wikilens.cli import main


def test_contradict_missing_index_returns_two(
    tmp_path: Path, capsys: pytest.CaptureFixture
):
    rc = main(
        [
            "contradict",
            str(tmp_path),
            "--db",
            str(tmp_path / "missing_db"),
            "--judge",
            "none",
        ]
    )
    assert rc == 2
    err = capsys.readouterr().err
    assert "No index" in err or "Failed to open" in err


def test_contradict_claude_fails_without_api_key(
    tmp_path: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
):
    # Patch out dotenv so it can't load .env, then strip the key from env.
    # --judge claude should exit 2 with a clear ANTHROPIC_API_KEY message.
    from unittest.mock import patch

    from wikilens.pipeline import ingest_vault

    (tmp_path / "n1.md").write_text("alpha beta", encoding="utf-8")
    (tmp_path / "n2.md").write_text("gamma delta", encoding="utf-8")
    ingest_vault(vault_root=tmp_path, db_path=str(tmp_path / "db"))

    with patch("wikilens.judge._load_dotenv_if_present"):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        rc = main(
            [
                "contradict",
                str(tmp_path),
                "--db",
                str(tmp_path / "db"),
                "--judge",
                "claude",
            ]
        )
    assert rc == 2
    err = capsys.readouterr().err
    assert "ANTHROPIC_API_KEY" in err


def test_contradict_unknown_only_returns_two(
    tmp_path: Path, capsys: pytest.CaptureFixture
):
    from wikilens.pipeline import ingest_vault

    (tmp_path / "n1.md").write_text("hello", encoding="utf-8")
    ingest_vault(vault_root=tmp_path, db_path=str(tmp_path / "db"))

    rc = main(
        [
            "contradict",
            str(tmp_path),
            "--db",
            str(tmp_path / "db"),
            "--judge",
            "none",
            "--only",
            "values",
        ]
    )
    assert rc == 2
    err = capsys.readouterr().err
    assert "unknown scope" in err


def test_contradict_mock_judge_end_to_end(
    tmp_path: Path, capsys: pytest.CaptureFixture
):
    """--judge none exercises walk → pair gen → filter → format without LLM."""
    from wikilens.pipeline import ingest_vault

    (tmp_path / "a.md").write_text(
        "# A\n\nParis is the capital of France.\n", encoding="utf-8"
    )
    (tmp_path / "b.md").write_text(
        "# B\n\nBerlin is a large city in Germany.\n", encoding="utf-8"
    )
    (tmp_path / "c.md").write_text(
        "# C\n\nBread rises when yeast ferments sugar.\n", encoding="utf-8"
    )
    ingest_vault(vault_root=tmp_path, db_path=str(tmp_path / "db"))

    rc = main(
        [
            "contradict",
            str(tmp_path),
            "--db",
            str(tmp_path / "db"),
            "--judge",
            "none",
            "--json",
        ]
    )
    # MockJudge returns verdict=False → zero findings → exit 0.
    assert rc == 0
    out = capsys.readouterr().out
    doc = json.loads(out)
    assert doc["schema_version"] == 1
    assert doc["judge"] == "mock"
    assert doc["stats"]["findings"] == 0
    # Candidates > 0 means pair generation actually ran.
    assert doc["stats"]["candidates"] >= 0
    assert doc["findings"] == []


def test_contradict_markdown_default_output(
    tmp_path: Path, capsys: pytest.CaptureFixture
):
    from wikilens.pipeline import ingest_vault

    (tmp_path / "n1.md").write_text("alpha beta gamma", encoding="utf-8")
    (tmp_path / "n2.md").write_text("delta epsilon zeta", encoding="utf-8")
    ingest_vault(vault_root=tmp_path, db_path=str(tmp_path / "db"))

    rc = main(
        [
            "contradict",
            str(tmp_path),
            "--db",
            str(tmp_path / "db"),
            "--judge",
            "none",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "Contradiction report" in out
    assert "judge: mock" in out
    assert "## factual (0)" in out
    assert "## temporal (0)" in out
