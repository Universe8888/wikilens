"""Tests for the `wikilens gap` CLI subcommand (P5, Phase 5.1).

Covers the plumbing path only: exit codes, bad input, unsupported
generator backends, and --judge none end-to-end against a real tiny
ingest. No network, no Claude.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from wikilens.cli import main


def test_gap_missing_index_returns_two(
    tmp_path: Path, capsys: pytest.CaptureFixture
):
    rc = main(
        [
            "gap",
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


def test_gap_claude_fails_without_api_key(
    tmp_path: Path, capsys: pytest.CaptureFixture, monkeypatch: pytest.MonkeyPatch
):
    from unittest.mock import patch

    from wikilens.pipeline import ingest_vault

    (tmp_path / "a.md").write_text("alpha beta gamma", encoding="utf-8")
    (tmp_path / "b.md").write_text("delta epsilon zeta", encoding="utf-8")
    (tmp_path / "c.md").write_text("eta theta iota", encoding="utf-8")
    ingest_vault(vault_root=tmp_path, db_path=str(tmp_path / "db"))

    with patch("wikilens.generator.load_dotenv_if_present"):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        rc = main(
            [
                "gap",
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


def test_gap_mock_generator_end_to_end_json(
    tmp_path: Path, capsys: pytest.CaptureFixture
):
    """--judge none exercises walk → cluster → generate → format without LLM."""
    from wikilens.pipeline import ingest_vault

    # Need enough chunks to actually cluster. Write a handful of single-paragraph
    # notes; each becomes one chunk.
    topics = [
        ("bio1.md", "Photosynthesis converts light energy into chemical energy in plants."),
        ("bio2.md", "Chlorophyll is the primary pigment that absorbs light during photosynthesis."),
        ("bio3.md", "Leaves have chloroplasts: specialized cells where photosynthesis happens."),
        ("phys1.md", "Newton described the three laws of motion in the Principia."),
        ("phys2.md", "The second law of motion relates force, mass, and acceleration."),
        ("phys3.md", "Kepler's laws describe the motion of planets around the sun."),
    ]
    for name, body in topics:
        (tmp_path / name).write_text(f"# Note\n\n{body}\n", encoding="utf-8")
    ingest_vault(vault_root=tmp_path, db_path=str(tmp_path / "db"))

    rc = main(
        [
            "gap",
            str(tmp_path),
            "--db",
            str(tmp_path / "db"),
            "--judge",
            "none",
            "--min-cluster-size",
            "2",
            "--k",
            "2",
            "--json",
        ]
    )
    # MockGenerator always returns one gap per cluster → findings > 0 → exit 1.
    assert rc == 1
    out = capsys.readouterr().out
    doc = json.loads(out)
    assert doc["schema_version"] == 1
    assert doc["generator"] == "mock"
    assert doc["stats"]["chunks"] == 6
    assert doc["stats"]["clusters"] >= 1
    assert doc["stats"]["findings"] >= 1
    # Clusters list is present and chunk IDs resolve.
    assert len(doc["clusters"]) >= 1
    assert all("chunk_ids" in c for c in doc["clusters"])
    # Every finding has a kebab-case title.
    for f in doc["findings"]:
        assert f["suggested_note_title"]
        assert " " not in f["suggested_note_title"]


def test_gap_markdown_default_output(
    tmp_path: Path, capsys: pytest.CaptureFixture
):
    from wikilens.pipeline import ingest_vault

    # Enough chunks to form at least one cluster of min_cluster_size=2.
    for i, body in enumerate(["alpha beta gamma", "delta epsilon zeta", "eta theta iota"]):
        (tmp_path / f"n{i}.md").write_text(body, encoding="utf-8")
    ingest_vault(vault_root=tmp_path, db_path=str(tmp_path / "db"))

    rc = main(
        [
            "gap",
            str(tmp_path),
            "--db",
            str(tmp_path / "db"),
            "--judge",
            "none",
            "--min-cluster-size",
            "2",
            "--k",
            "1",
        ]
    )
    # 1 cluster of 3 → 1 finding → exit 1.
    assert rc == 1
    out = capsys.readouterr().out
    assert "Gap report" in out
    assert "generator: mock" in out
    assert "Cluster" in out
    assert "Suggested note:" in out


def test_gap_no_clusters_returns_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture
):
    """Vault too small to form any cluster → no findings → exit 0."""
    from wikilens.pipeline import ingest_vault

    # Two chunks, min_cluster_size=3 → no surviving clusters.
    (tmp_path / "a.md").write_text("alpha", encoding="utf-8")
    (tmp_path / "b.md").write_text("beta", encoding="utf-8")
    ingest_vault(vault_root=tmp_path, db_path=str(tmp_path / "db"))

    rc = main(
        [
            "gap",
            str(tmp_path),
            "--db",
            str(tmp_path / "db"),
            "--judge",
            "none",
            "--min-cluster-size",
            "3",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "no gaps found" in out.lower()


def test_gap_sample_caps_generator_calls(
    tmp_path: Path, capsys: pytest.CaptureFixture
):
    """--sample 1 should produce at most 1 cluster's worth of findings."""
    from wikilens.pipeline import ingest_vault

    topics = [
        ("bio1.md", "Photosynthesis needs light."),
        ("bio2.md", "Chlorophyll absorbs light for photosynthesis."),
        ("phys1.md", "Newton described gravity."),
        ("phys2.md", "Kepler described orbits under gravity."),
    ]
    for name, body in topics:
        (tmp_path / name).write_text(body, encoding="utf-8")
    ingest_vault(vault_root=tmp_path, db_path=str(tmp_path / "db"))

    rc = main(
        [
            "gap",
            str(tmp_path),
            "--db",
            str(tmp_path / "db"),
            "--judge",
            "none",
            "--min-cluster-size",
            "2",
            "--k",
            "2",
            "--sample",
            "1",
            "--top-gaps-per-cluster",
            "1",
            "--json",
        ]
    )
    assert rc == 1
    out = capsys.readouterr().out
    doc = json.loads(out)
    # clusters_processed should respect the sample cap.
    assert doc["stats"]["clusters_processed"] == 1
    # MockGenerator with top_gaps=1 and sample=1 → exactly one finding.
    assert doc["stats"]["findings"] == 1
