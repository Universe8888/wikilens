"""Shared environment helpers."""

from __future__ import annotations

from pathlib import Path


def load_dotenv_if_present() -> None:
    """Load .env from the repo root if python-dotenv is installed.

    Uses override=False so a key already set in the shell always wins.
    """
    try:
        from dotenv import load_dotenv

        env_path = Path(__file__).parent.parent.parent / ".env"
        if env_path.exists():
            load_dotenv(env_path, override=False)
    except ImportError:
        pass
