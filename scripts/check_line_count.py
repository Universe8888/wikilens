#!/usr/bin/env python3
"""Warn (or fail with --strict) if any src/wikilens/ file exceeds 500 lines.

Runs as warning-only until M2 lands (cli.py split). Pass --strict to hard-fail.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

MAX_LINES = 500
SRC_DIR = Path("src/wikilens")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict", action="store_true", help="Exit 1 on violations")
    args = parser.parse_args()

    violations: list[tuple[Path, int]] = []
    for py in sorted(SRC_DIR.rglob("*.py")):
        count = len(py.read_text(encoding="utf-8").splitlines())
        if count > MAX_LINES:
            violations.append((py, count))

    if violations:
        for path, count in violations:
            level = "ERROR" if args.strict else "WARNING"
            print(f"{level}: {path}: {count} lines (max {MAX_LINES})", file=sys.stderr)
        if args.strict:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
