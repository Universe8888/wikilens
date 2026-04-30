#!/usr/bin/env python3
"""Pre-commit sanitization gate.

Scans the staged diff (or a given path set) for strings that must never
appear in tracked files of this public repo. Exit code 1 on any hit;
0 on a clean sweep.

The prohibited list is intentionally narrow — it blocks the specific
leak patterns that already happened once on this repo (see
.local/AGENT_BRIEFING.md for the rationale). Add entries sparingly:
false positives here will be ignored and the gate will stop working.

Usage:
    python scripts/check_sanitization.py                # scan staged diff
    python scripts/check_sanitization.py --all-tracked  # scan every tracked file
    python scripts/check_sanitization.py path1 path2    # scan given files

Wire as a git pre-commit hook:
    cp scripts/check_sanitization.py .git/hooks/pre-commit
    chmod +x .git/hooks/pre-commit
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

# Each entry: (regex, human-readable reason). Case-insensitive.
# Patterns are crafted to avoid matching themselves inside this file —
# if you add a new one, verify it doesn't flag its own definition.
PROHIBITED: list[tuple[str, str]] = [
    (r"\bDraft\s*Kings\b", "employer name"),
    (r"\bprocurement\b", "day-job domain"),
    (r"\bITAM\b", "day-job domain"),
    (r"Lead\s+Procurement", "job title"),
    (r"\bb\.manzov\b", "username in path"),
    (r"C:\\\\Users\\\\b\.manzov", "absolute user path"),
    (r"My-Working-Memory-Agent", "private wiki path"),
    (r"my-wiki-personal", "private wiki path"),
    (r"IBM\s+Agent\s+Developer", "cert in career context"),
    (r"Vanderbilt\s+RAG", "cert in career context"),
]

# Files we never scan, even if they match a glob. Adding a path here is
# equivalent to saying "this file is expected to contain prohibited
# strings and is protected from publication by other means."
ALLOWLIST = {
    "scripts/check_sanitization.py",  # this file's own regex list
}


def _staged_files() -> list[Path]:
    """Paths staged for commit (added, modified, renamed — not deleted)."""
    try:
        out = subprocess.check_output(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"sanitization: could not query staged files: {e}", file=sys.stderr)
        sys.exit(2)
    return [Path(p) for p in out.splitlines() if p]


def _all_tracked_files() -> list[Path]:
    try:
        out = subprocess.check_output(["git", "ls-files"], text=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"sanitization: could not list tracked files: {e}", file=sys.stderr)
        sys.exit(2)
    return [Path(p) for p in out.splitlines() if p]


def _scan_file(path: Path, patterns: list[tuple[re.Pattern, str]]) -> list[tuple[int, str, str]]:
    """Return list of (line_number, reason, excerpt) hits for a single file."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    hits: list[tuple[int, str, str]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for pat, reason in patterns:
            if pat.search(line):
                excerpt = line.strip()[:120]
                hits.append((lineno, reason, excerpt))
    return hits


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--all-tracked",
        action="store_true",
        help="Scan every tracked file (not just staged). Useful for CI.",
    )
    parser.add_argument("paths", nargs="*", help="Explicit paths to scan.")
    args = parser.parse_args(argv)

    if args.paths:
        targets = [Path(p) for p in args.paths]
    elif args.all_tracked:
        targets = _all_tracked_files()
    else:
        targets = _staged_files()

    targets = [p for p in targets if p.as_posix() not in ALLOWLIST and p.is_file()]

    if not targets:
        return 0

    compiled = [(re.compile(pat, re.IGNORECASE), reason) for pat, reason in PROHIBITED]

    total_hits = 0
    for path in targets:
        for lineno, reason, excerpt in _scan_file(path, compiled):
            print(f"{path}:{lineno}: [{reason}] {excerpt}", file=sys.stderr)
            total_hits += 1

    if total_hits:
        print(
            f"\nsanitization: {total_hits} prohibited string(s) found. "
            "Move content to .local/ or rephrase, then retry.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
