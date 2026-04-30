"""wikilens CLI entry point.

P1 scaffolding — commands are stubbed until P2 (ingestion + RAG core).
"""

from __future__ import annotations

import sys

from wikilens import __version__

USAGE = """\
wikilens {version}

Usage:
  wikilens ingest <vault-path>        (P2 — not implemented)
  wikilens query "<question>"         (P2 — not implemented)
  wikilens audit links                (P3 — not implemented)
  wikilens find contradictions        (P4 — not implemented)
  wikilens find gaps                  (P6 — not implemented)
  wikilens benchmark                  (P5 — not implemented)
  wikilens --version
"""


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]

    if not args or args[0] in {"-h", "--help"}:
        print(USAGE.format(version=__version__))
        return 0

    if args[0] in {"-V", "--version"}:
        print(__version__)
        return 0

    print(f"wikilens: '{args[0]}' is not available yet (pre-alpha).")
    print("See README.md for the roadmap.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
