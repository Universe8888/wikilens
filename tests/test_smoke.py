"""Smoke tests — verifies the package imports and CLI is wired."""

from __future__ import annotations

import pytest

from wikilens import __version__
from wikilens.cli import main


def test_version_is_set():
    assert __version__


def test_cli_no_args_shows_help(capsys):
    rc = main([])
    captured = capsys.readouterr()
    assert rc == 0
    assert "wikilens" in captured.out.lower()


def test_cli_version_flag(capsys):
    # argparse --version calls sys.exit(0) after printing.
    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert __version__ in captured.out


def test_cli_query_without_index_exits_nonzero(tmp_path, capsys):
    # Run against a fresh empty directory where no DB exists.
    rc = main(["query", "anything", "--db", str(tmp_path / "no-db")])
    assert rc == 2
    assert "ingest" in capsys.readouterr().err.lower()
