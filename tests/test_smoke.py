"""Smoke tests — verifies the package imports and CLI is wired."""

from wikilens import __version__
from wikilens.cli import main


def test_version_is_set():
    assert __version__


def test_cli_help_exits_zero(capsys):
    rc = main(["--help"])
    captured = capsys.readouterr()
    assert rc == 0
    assert "wikilens" in captured.out


def test_cli_version_prints_version(capsys):
    rc = main(["--version"])
    captured = capsys.readouterr()
    assert rc == 0
    assert __version__ in captured.out


def test_cli_unknown_command_exits_nonzero():
    rc = main(["ingest", "./nowhere"])
    assert rc == 2
