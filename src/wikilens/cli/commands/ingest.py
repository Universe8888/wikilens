"""wikilens ingest — index a markdown vault."""

from __future__ import annotations

import argparse
from pathlib import Path

from wikilens.cli._common import DEFAULT_DB_PATH, warn_if_first_run


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("ingest", help="Index a markdown vault.")
    p.add_argument("vault_path", type=Path)
    p.add_argument("--db", default=DEFAULT_DB_PATH, help="Store path (default: %(default)s)")
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    warn_if_first_run()
    from wikilens.pipeline import ingest_vault

    report = ingest_vault(
        vault_root=args.vault_path,
        db_path=args.db,
    )
    print(report.summary())
    return 0
