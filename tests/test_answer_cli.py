"""CLI integration tests for `wikilens answer` (P6.1 steps 8 + 9).

Uses a real tiny vault ingest (matching the pattern in test_gap_cli.py /
test_contradict_cli.py) so the store and embedder are genuine. The drafter
is always MockDrafter via ``--judge none`` so no API calls are made.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from wikilens.cli import main
from wikilens.pipeline import ingest_vault

# ─── shared fixture ───────────────────────────────────────────────────────────


@pytest.fixture()
def tiny_vault(tmp_path: Path) -> tuple[Path, Path]:
    """Three small notes + a real ingested index. Returns (vault, db_path)."""
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "photosynthesis.md").write_text(
        "# Light reactions\n"
        "Light reactions produce ATP and NADPH in the thylakoid membranes. "
        "The products are passed to a second stage for carbon fixation.",
        encoding="utf-8",
    )
    (vault / "chlorophyll.md").write_text(
        "# Chlorophyll\n"
        "Chlorophyll a absorbs photons at 680nm. "
        "It is found in Photosystem I and Photosystem II.",
        encoding="utf-8",
    )
    (vault / "cooking.md").write_text(
        "# Cast iron care\n"
        "Cast iron pans require regular seasoning to maintain their surface. "
        "They reward high-heat searing.",
        encoding="utf-8",
    )
    db_path = tmp_path / "db"
    ingest_vault(vault_root=vault, db_path=str(db_path))
    return vault, db_path


def _write_gaps_json(path: Path, findings: list[dict] | None = None) -> Path:
    findings = findings or [
        {
            "cluster_id": 0,
            "cluster_size": 3,
            "gap_question": "What is the Calvin cycle?",
            "suggested_note_title": "calvin-cycle",
            "rationale": "notes describe light reactions but not dark",
            "supporting_chunk_ids": [],
        }
    ]
    path.write_text(
        json.dumps({"schema_version": 1, "findings": findings}),
        encoding="utf-8",
    )
    return path


# ─── input validation ─────────────────────────────────────────────────────────


def test_answer_missing_gaps_arg_exits_nonzero(tiny_vault: tuple[Path, Path]):
    vault, db = tiny_vault
    # argparse calls sys.exit(2) on a missing required argument.
    with pytest.raises(SystemExit) as exc_info:
        main(["answer", str(vault), "--db", str(db)])
    assert exc_info.value.code != 0


def test_answer_gaps_file_not_found_exits_2(tiny_vault: tuple[Path, Path], tmp_path: Path):
    vault, db = tiny_vault
    rc = main([
        "answer", str(vault),
        "--gaps", str(tmp_path / "nonexistent.json"),
        "--judge", "none",
        "--db", str(db),
    ])
    assert rc == 2


def test_answer_write_without_out_exits_2(tiny_vault: tuple[Path, Path], tmp_path: Path):
    vault, db = tiny_vault
    gaps_file = _write_gaps_json(tmp_path / "gaps.json")
    rc = main([
        "answer", str(vault),
        "--gaps", str(gaps_file),
        "--judge", "none",
        "--db", str(db),
        "--write",  # no --out
    ])
    assert rc == 2


def test_answer_empty_index_exits_2(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    empty_db = tmp_path / "empty_db"
    gaps_file = _write_gaps_json(tmp_path / "gaps.json")
    rc = main([
        "answer", str(vault),
        "--gaps", str(gaps_file),
        "--judge", "none",
        "--db", str(empty_db),
    ])
    assert rc == 2


def test_answer_invalid_gaps_json_exits_2(tiny_vault: tuple[Path, Path], tmp_path: Path):
    vault, db = tiny_vault
    bad_file = tmp_path / "bad.json"
    bad_file.write_text("not json {")
    rc = main([
        "answer", str(vault),
        "--gaps", str(bad_file),
        "--judge", "none",
        "--db", str(db),
    ])
    assert rc == 2


# ─── mock-judge dry-runs ──────────────────────────────────────────────────────


def test_answer_judge_none_produces_markdown_output(
    tiny_vault: tuple[Path, Path], tmp_path: Path, capsys: pytest.CaptureFixture
):
    vault, db = tiny_vault
    gaps_file = _write_gaps_json(tmp_path / "gaps.json")
    rc = main([
        "answer", str(vault),
        "--gaps", str(gaps_file),
        "--judge", "none",
        "--db", str(db),
        "--retrieval-mode", "hybrid",
        "--min-supporting", "1",
    ])
    out = capsys.readouterr().out
    assert "Answer report" in out
    assert rc in (0, 1)


def test_answer_judge_none_json_output_is_valid(
    tiny_vault: tuple[Path, Path], tmp_path: Path, capsys: pytest.CaptureFixture
):
    vault, db = tiny_vault
    gaps_file = _write_gaps_json(tmp_path / "gaps.json")
    main([
        "answer", str(vault),
        "--gaps", str(gaps_file),
        "--judge", "none",
        "--db", str(db),
        "--retrieval-mode", "hybrid",
        "--min-supporting", "1",
        "--json",
    ])
    doc = json.loads(capsys.readouterr().out)
    assert doc["schema_version"] == 1
    assert len(doc["drafts"]) == 1
    assert doc["drafts"][0]["gap_id"] == "calvin-cycle"


def test_answer_exit_0_when_all_drafted(
    tiny_vault: tuple[Path, Path], tmp_path: Path, capsys: pytest.CaptureFixture
):
    vault, db = tiny_vault
    gaps_file = _write_gaps_json(tmp_path / "gaps.json")
    rc = main([
        "answer", str(vault),
        "--gaps", str(gaps_file),
        "--judge", "none",
        "--db", str(db),
        "--retrieval-mode", "hybrid",
        "--min-supporting", "1",
    ])
    assert rc == 0


def test_answer_exit_1_when_external_research(
    tiny_vault: tuple[Path, Path], tmp_path: Path, capsys: pytest.CaptureFixture
):
    vault, db = tiny_vault
    gaps_file = _write_gaps_json(tmp_path / "gaps.json")
    rc = main([
        "answer", str(vault),
        "--gaps", str(gaps_file),
        "--judge", "none",
        "--db", str(db),
        "--retrieval-mode", "hybrid",
        "--min-supporting", "999",  # forces external-research
    ])
    assert rc == 1


def test_answer_sample_caps_output(
    tiny_vault: tuple[Path, Path], tmp_path: Path, capsys: pytest.CaptureFixture
):
    vault, db = tiny_vault
    findings = [
        {**{"cluster_id": i, "cluster_size": 3, "gap_question": f"q{i}?",
            "suggested_note_title": f"gap-{i}", "rationale": "r",
            "supporting_chunk_ids": []}}
        for i in range(4)
    ]
    gaps_file = _write_gaps_json(tmp_path / "gaps.json", findings)
    main([
        "answer", str(vault),
        "--gaps", str(gaps_file),
        "--judge", "none",
        "--db", str(db),
        "--retrieval-mode", "hybrid",
        "--min-supporting", "1",
        "--sample", "2",
        "--json",
    ])
    doc = json.loads(capsys.readouterr().out)
    assert len(doc["drafts"]) == 2


# ─── --write --out ────────────────────────────────────────────────────────────


def test_answer_write_creates_stub_file(
    tiny_vault: tuple[Path, Path], tmp_path: Path
):
    vault, db = tiny_vault
    gaps_file = _write_gaps_json(tmp_path / "gaps.json")
    out_dir = tmp_path / "stubs"
    rc = main([
        "answer", str(vault),
        "--gaps", str(gaps_file),
        "--judge", "none",
        "--db", str(db),
        "--retrieval-mode", "hybrid",
        "--min-supporting", "1",
        "--write",
        "--out", str(out_dir),
    ])
    assert rc in (0, 1)
    assert (out_dir / "calvin-cycle.md").exists()
    content = (out_dir / "calvin-cycle.md").read_text(encoding="utf-8")
    assert "generated_by: wikilens-answer" in content


def test_answer_write_collision_exits_2(
    tiny_vault: tuple[Path, Path], tmp_path: Path, capsys: pytest.CaptureFixture
):
    vault, db = tiny_vault
    gaps_file = _write_gaps_json(tmp_path / "gaps.json")
    out_dir = tmp_path / "stubs"
    out_dir.mkdir()
    (out_dir / "calvin-cycle.md").write_text("existing content")

    rc = main([
        "answer", str(vault),
        "--gaps", str(gaps_file),
        "--judge", "none",
        "--db", str(db),
        "--retrieval-mode", "hybrid",
        "--min-supporting", "1",
        "--write",
        "--out", str(out_dir),
    ])
    assert rc == 2
    assert (out_dir / "calvin-cycle.md").read_text() == "existing content"


# ─── API key guard ────────────────────────────────────────────────────────────


def test_answer_openai_fails_without_api_key(
    tiny_vault: tuple[Path, Path], tmp_path: Path, capsys: pytest.CaptureFixture
):
    vault, db = tiny_vault
    gaps_file = _write_gaps_json(tmp_path / "gaps.json")
    with (
        patch("wikilens.drafter.load_dotenv_if_present"),
        pytest.MonkeyPatch().context() as mp,
    ):
        mp.delenv("OPENAI_API_KEY", raising=False)
        rc = main([
            "answer", str(vault),
            "--gaps", str(gaps_file),
            "--judge", "openai",
            "--db", str(db),
        ])
    assert rc == 2
    assert "OPENAI_API_KEY" in capsys.readouterr().err


def test_answer_claude_fails_without_api_key(
    tiny_vault: tuple[Path, Path], tmp_path: Path, capsys: pytest.CaptureFixture
):
    vault, db = tiny_vault
    gaps_file = _write_gaps_json(tmp_path / "gaps.json")
    with (
        patch("wikilens.drafter.load_dotenv_if_present"),
        pytest.MonkeyPatch().context() as mp,
    ):
        mp.delenv("ANTHROPIC_API_KEY", raising=False)
        rc = main([
            "answer", str(vault),
            "--gaps", str(gaps_file),
            "--judge", "claude",
            "--db", str(db),
        ])
    assert rc == 2
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().err
