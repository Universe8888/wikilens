"""wikilens CLI entry point."""

from __future__ import annotations

import argparse
import sys

from wikilens import __version__
from wikilens.cli.commands import (
    answer,
    audit,
    concepts,
    confidence,
    contradict,
    drift,
    gap,
    ingest,
    query,
)


def _cmd_stub(name: str, phase: str):
    def _fn(args: argparse.Namespace) -> int:
        print(f"wikilens: '{name}' is not available yet ({phase}).")
        return 2

    return _fn


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wikilens",
        description="Agentic intelligence layer for Markdown/Obsidian vaults.",
    )
    parser.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command")

    ingest.register(sub)
    query.register(sub)
    audit.register(sub)
    contradict.register(sub)
    gap.register(sub)
    answer.register(sub)
    drift.register(sub)
    concepts.register(sub)
    confidence.register(sub)

    for name, phase in [
        ("benchmark", "P7"),
    ]:
        p = sub.add_parser(name, help=f"({phase} — not implemented)")
        p.set_defaults(func=_cmd_stub(name, phase))

    return parser


def _force_stdout_utf8() -> None:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    _force_stdout_utf8()

    parser = _build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 0
    try:
        return args.func(args)
    except Exception as exc:
        from wikilens.cost import BudgetExceeded

        if isinstance(exc, BudgetExceeded):
            print("wikilens: budget cap exceeded, aborting.", file=sys.stderr)
            return 2
        raise


if __name__ == "__main__":
    raise SystemExit(main())
