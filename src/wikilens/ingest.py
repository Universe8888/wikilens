"""Vault ingestion primitives.

Grows across P2 steps 2-5:
  - step 2: vault walker
  - step 3: frontmatter parser (this commit)
  - step 4: wikilink / tag / embed extractor
  - step 5: heading-aware chunker
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_INCLUDE: tuple[str, ...] = ("**/*.md",)
DEFAULT_EXCLUDE: tuple[str, ...] = ()

# Matches a YAML frontmatter block at the very start of a file:
#   ---\n ... \n---\n
# Allows CRLF/LF. The block must be the first thing in the file (no BOM-aware
# handling — caller should pass decoded text).
_FRONTMATTER_RE = re.compile(
    r"\A---[ \t]*\r?\n(?P<fm>(?:.*\r?\n)*?)---[ \t]*\r?\n?(?P<body>.*)\Z",
    re.DOTALL,
)


@dataclass(frozen=True)
class Note:
    """A parsed note: source path, frontmatter dict, and body text.

    `frontmatter` is always a dict (possibly empty) — if the file had no
    frontmatter, it is `{}`. If the frontmatter was malformed or non-mapping,
    `frontmatter` is `{}` and `frontmatter_error` describes why.
    """

    path: Path
    frontmatter: dict[str, Any]
    body: str
    frontmatter_error: str | None = None


def walk_vault(
    root: str | Path,
    include: Iterable[str] = DEFAULT_INCLUDE,
    exclude: Iterable[str] = DEFAULT_EXCLUDE,
) -> list[Path]:
    """Discover Markdown notes in a vault.

    Args:
        root: Vault root directory.
        include: Glob patterns (relative to root) to include. Defaults to all `.md`.
        exclude: Glob patterns (relative to root) to exclude.

    Returns:
        Sorted list of absolute file paths matching `include` minus `exclude`.

    Raises:
        FileNotFoundError: If `root` does not exist.
        NotADirectoryError: If `root` exists but is not a directory.
    """
    root_path = Path(root).resolve()
    if not root_path.exists():
        raise FileNotFoundError(f"vault root does not exist: {root_path}")
    if not root_path.is_dir():
        raise NotADirectoryError(f"vault root is not a directory: {root_path}")

    matched: set[Path] = set()
    for pattern in include:
        matched.update(p for p in root_path.glob(pattern) if p.is_file())

    excluded: set[Path] = set()
    for pattern in exclude:
        excluded.update(p for p in root_path.glob(pattern) if p.is_file())

    return sorted(matched - excluded)


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str, str | None]:
    """Split raw note text into (frontmatter_dict, body, error).

    - No frontmatter fence → ({}, original_text, None)
    - Valid YAML mapping frontmatter → (dict, body_after_fence, None)
    - Empty frontmatter block (just `---\\n---`) → ({}, body, None)
    - Malformed YAML → ({}, body_after_fence, "<yaml error>")
    - Valid YAML but non-mapping (e.g. a scalar or list) → ({}, body_after_fence,
      "frontmatter is not a mapping")
    """
    match = _FRONTMATTER_RE.match(text)
    if match is None:
        return {}, text, None

    fm_text = match.group("fm")
    body = match.group("body")

    if not fm_text.strip():
        return {}, body, None

    try:
        loaded = yaml.safe_load(fm_text)
    except yaml.YAMLError as e:
        return {}, body, f"yaml error: {e}"

    if loaded is None:
        return {}, body, None
    if not isinstance(loaded, dict):
        return {}, body, "frontmatter is not a mapping"
    return loaded, body, None


def parse_note(path: str | Path) -> Note:
    """Read a markdown file and parse its frontmatter + body.

    Reads as UTF-8 with BOM tolerance. Never raises on malformed frontmatter —
    the error is captured on the returned Note.
    """
    p = Path(path)
    text = p.read_text(encoding="utf-8-sig")
    fm, body, err = parse_frontmatter(text)
    return Note(path=p, frontmatter=fm, body=body, frontmatter_error=err)
