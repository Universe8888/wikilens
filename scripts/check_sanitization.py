#!/usr/bin/env python3
"""Pre-commit sanitization gate.

Scans staged file contents (or a given path set) for strings that must
never appear in tracked files of this public repo. Exit code 1 on any
hit; 0 on a clean sweep.

The prohibited list is intentionally narrow — it blocks the specific
leak patterns that already happened once on this repo (see
.local/AGENT_BRIEFING.md for the rationale). Add entries sparingly:
false positives here will be ignored and the gate will stop working.

Usage:
    python scripts/check_sanitization.py                # scan staged diff
    python scripts/check_sanitization.py --all-tracked  # scan every tracked file
    python scripts/check_sanitization.py path1 path2    # scan given files

Install through pre-commit:
    python -m pip install pre-commit
    pre-commit install
    pre-commit install --hook-type pre-push
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


class ScanReadError(RuntimeError):
    """Raised when a target cannot be read safely."""


def _repo_root() -> Path:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"sanitization: could not locate repository root: {e}", file=sys.stderr)
        sys.exit(2)
    return Path(out.strip()).resolve()


def _repo_relative_posix(path: Path, repo_root: Path) -> str:
    absolute = path if path.is_absolute() else repo_root / path
    try:
        relative = absolute.resolve().relative_to(repo_root)
    except ValueError:
        relative = path
    return relative.as_posix()


def _is_allowlisted(path: Path, repo_root: Path) -> bool:
    return _repo_relative_posix(path, repo_root) in ALLOWLIST


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


def _read_worktree_text(path: Path, repo_root: Path) -> str:
    target = path if path.is_absolute() else repo_root / path
    try:
        return target.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        raise ScanReadError(str(e)) from e


def _read_staged_text(path: Path, repo_root: Path) -> str:
    rel_path = _repo_relative_posix(path, repo_root)
    try:
        return subprocess.check_output(
            ["git", "show", f":{rel_path}"],
            cwd=repo_root,
            text=True,
            stderr=subprocess.DEVNULL,
            errors="replace",
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        raise ScanReadError(str(e)) from e


def _scan_text(
    label: str,
    text: str,
    patterns: list[tuple[re.Pattern, str]],
) -> list[tuple[str, int, str]]:
    """Return list of (label, line_number, reason) hits for text."""
    hits: list[tuple[str, int, str]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for pat, reason in patterns:
            if pat.search(line):
                hits.append((label, lineno, reason))
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

    repo_root = _repo_root()
    scan_staged = not args.paths and not args.all_tracked

    if args.paths:
        targets = [Path(p) for p in args.paths]
    elif args.all_tracked:
        targets = _all_tracked_files()
    else:
        targets = _staged_files()

    targets = [p for p in targets if not _is_allowlisted(p, repo_root)]

    if not targets:
        return 0

    compiled = [(re.compile(pat, re.IGNORECASE), reason) for pat, reason in PROHIBITED]

    total_hits = 0
    read_errors = 0
    for path in targets:
        label = _repo_relative_posix(path, repo_root)
        try:
            text = (
                _read_staged_text(path, repo_root)
                if scan_staged
                else _read_worktree_text(path, repo_root)
            )
        except ScanReadError:
            print(f"{label}: sanitization read failed", file=sys.stderr)
            read_errors += 1
            continue

        for hit_label, lineno, reason in _scan_text(label, text, compiled):
            print(
                f"{hit_label}:{lineno}: [{reason}] prohibited string found",
                file=sys.stderr,
            )
            total_hits += 1

    if read_errors:
        print(
            f"\nsanitization: {read_errors} file(s) could not be read safely.",
            file=sys.stderr,
        )
        return 2

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
