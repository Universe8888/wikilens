"""CLI end-to-end tests for `wikilens drift` (P8.4).

Uses tmp_path git repos + MockDriftJudge so no LLM calls or network.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from wikilens.cli import main

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo)] + list(args),
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test")
    return path


def _commit(repo: Path, rel: str, content: str, msg: str = "commit") -> str:
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    _git(repo, "add", rel)
    _git(repo, "commit", "-m", msg)
    return _git(repo, "rev-parse", "HEAD")


def _make_vault(tmp_path: Path) -> Path:
    """Minimal vault: one note with two revisions. Surface-edit only so
    MockDriftJudge (default no-drift) returns exit 0."""
    repo = _init_repo(tmp_path / "vault")
    _commit(repo, "note.md", "The sky is blue and also quite vast.", "v1")
    _commit(repo, "note.md", "The sky is blue and quite vast indeed.", "v2")
    return repo


# ---------------------------------------------------------------------------
# Help / version
# ---------------------------------------------------------------------------


def test_drift_appears_in_help(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "drift" in out


def test_drift_help(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["drift", "--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "--judge" in out
    assert "--min-score" in out
    assert "--sample" in out


# ---------------------------------------------------------------------------
# Exit codes
# ---------------------------------------------------------------------------


def test_drift_exit_0_no_findings(tmp_path, capsys):
    vault = _make_vault(tmp_path)
    # MockDriftJudge always returns no-drift → exit 0.
    rc = main(["drift", str(vault), "--judge", "none"])
    assert rc == 0


def test_drift_exit_2_not_a_git_repo(tmp_path, capsys):
    plain = tmp_path / "notarepo"
    plain.mkdir()
    (plain / "note.md").write_text("hello", encoding="utf-8")
    rc = main(["drift", str(plain), "--judge", "none"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "git" in err.lower() or "repository" in err.lower()


def test_drift_exit_2_path_does_not_exist(tmp_path, capsys):
    rc = main(["drift", str(tmp_path / "ghost"), "--judge", "none"])
    assert rc == 2


# ---------------------------------------------------------------------------
# Output shape
# ---------------------------------------------------------------------------


def test_drift_markdown_output_default(tmp_path, capsys):
    vault = _make_vault(tmp_path)
    rc = main(["drift", str(vault), "--judge", "none"])
    out = capsys.readouterr().out
    assert "# Temporal drift findings" in out
    assert rc == 0


def test_drift_json_output(tmp_path, capsys):
    vault = _make_vault(tmp_path)
    rc = main(["drift", str(vault), "--judge", "none", "--json"])
    out = capsys.readouterr().out
    doc = json.loads(out)
    assert doc["schema_version"] == 1
    assert "vault" in doc
    assert "findings" in doc
    assert rc == 0


def test_drift_json_stats_present(tmp_path, capsys):
    vault = _make_vault(tmp_path)
    main(["drift", str(vault), "--judge", "none", "--json"])
    out = capsys.readouterr().out
    doc = json.loads(out)
    assert "stats" in doc
    assert "walked_commits" in doc["stats"]


# ---------------------------------------------------------------------------
# --sample cap
# ---------------------------------------------------------------------------


def test_drift_sample_zero_judges_nothing(tmp_path, capsys):
    vault = _make_vault(tmp_path)
    main(["drift", str(vault), "--judge", "none", "--sample", "0", "--json"])
    out = capsys.readouterr().out
    doc = json.loads(out)
    assert doc["stats"]["pairs_judged"] == 0


# ---------------------------------------------------------------------------
# --only filter
# ---------------------------------------------------------------------------


def test_drift_only_nonexistent_note_produces_no_candidates(tmp_path, capsys):
    vault = _make_vault(tmp_path)
    rc = main(["drift", str(vault), "--judge", "none", "--only", "nosuchfile.md", "--json"])
    out = capsys.readouterr().out
    doc = json.loads(out)
    assert doc["stats"]["pairs_considered"] == 0
    assert rc == 0


# ---------------------------------------------------------------------------
# --granularity
# ---------------------------------------------------------------------------


def test_drift_granularity_paragraph_runs_without_error(tmp_path, capsys):
    vault = _make_vault(tmp_path)
    rc = main(["drift", str(vault), "--judge", "none", "--granularity", "paragraph"])
    assert rc == 0


# ---------------------------------------------------------------------------
# Vault is a sub-directory of the repo
# ---------------------------------------------------------------------------


def test_drift_vault_is_subdirectory(tmp_path, capsys):
    repo = _init_repo(tmp_path / "repo")
    _commit(repo, "notes/bio.md", "Cells are the basic unit of life.", "v1")
    _commit(repo, "notes/bio.md", "Cells are the fundamental unit of life.", "v2")
    notes_dir = repo / "notes"
    rc = main(["drift", str(notes_dir), "--judge", "none"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "# Temporal drift findings" in out


# ---------------------------------------------------------------------------
# Single-revision note skipped
# ---------------------------------------------------------------------------


def test_drift_single_revision_note_skipped(tmp_path, capsys):
    repo = _init_repo(tmp_path / "repo")
    _commit(repo, "only_once.md", "This note was never changed.", "v1")
    rc = main(["drift", str(repo), "--judge", "none", "--json"])
    out = capsys.readouterr().out
    doc = json.loads(out)
    assert doc["stats"]["pairs_considered"] == 0
    assert rc == 0
