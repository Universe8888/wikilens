"""wikilens audit — find broken, one-way, orphan, and shadowed wikilinks."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "audit",
        help="Find broken, one-way, orphan, and shadowed wikilinks in a vault.",
    )
    p.add_argument("vault_path", type=Path)
    p.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of markdown (schema is stable; see audit_format.py).",
    )
    p.add_argument(
        "--only",
        default="",
        help=(
            "Comma-separated defect classes to include "
            "(broken,one-way,orphan,shadowed). Default: all."
        ),
    )
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    from wikilens.audit import audit_vault
    from wikilens.audit_format import ALL_CLASSES, format_json, format_markdown

    only_tuple: tuple[str, ...] | None = None
    if args.only:
        requested = [c.strip() for c in args.only.split(",") if c.strip()]
        invalid = [c for c in requested if c not in ALL_CLASSES]
        if invalid:
            print(
                f"wikilens audit: unknown class(es): {', '.join(invalid)}. "
                f"Valid: {', '.join(ALL_CLASSES)}",
                file=sys.stderr,
            )
            return 2
        only_tuple = tuple(requested)  # type: ignore[assignment]

    report = audit_vault(args.vault_path)

    if args.json:
        sys.stdout.write(format_json(report, only=only_tuple))  # type: ignore[arg-type]
    else:
        sys.stdout.write(format_markdown(report, only=only_tuple))  # type: ignore[arg-type]

    return 1 if report.total_findings > 0 else 0
