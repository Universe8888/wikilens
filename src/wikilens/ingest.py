"""Vault ingestion primitives.

Grows across P2 steps 2-5:
  - step 2: vault walker
  - step 3: frontmatter parser
  - step 4: wikilink / tag / embed extractor (this commit)
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


@dataclass(frozen=True)
class Wikilink:
    """A parsed `[[target]]` or `[[target|alias]]` or `[[target#heading]]` link."""

    target: str  # page name, e.g. "Photosynthesis"
    heading: str | None  # after '#', None if absent
    alias: str | None  # after '|', None if absent
    is_embed: bool  # True if the source was `![[...]]`
    raw: str  # the raw matched text, for debugging


@dataclass(frozen=True)
class NoteLinks:
    """Extraction result for a single note body."""

    wikilinks: tuple[Wikilink, ...]
    tags: tuple[str, ...]  # without the leading '#'
    markdown_links: tuple[tuple[str, str], ...]  # (display_text, url_or_path)


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


# --- link extraction ------------------------------------------------------

# Strip fenced code blocks (```...``` or ~~~...~~~) and inline code (`...`)
# before running link regexes — otherwise `#` in code or `[[` in examples
# produces false positives.
_FENCED_CODE_RE = re.compile(
    r"^([`~]{3,})[^\n]*\n.*?^\1[ \t]*$",
    re.MULTILINE | re.DOTALL,
)
_INLINE_CODE_RE = re.compile(r"`[^`\n]+`")

# [[target]], [[target|alias]], [[target#heading]], [[target#heading|alias]]
# Optional leading '!' means embed. Target cannot contain ] [ | or newline.
_WIKILINK_RE = re.compile(
    r"(?P<embed>!)?\[\["
    r"(?P<target>[^\[\]\|\#\n]+?)"
    r"(?:#(?P<heading>[^\[\]\|\n]+?))?"
    r"(?:\|(?P<alias>[^\[\]\n]+?))?"
    r"\]\]"
)

# Tags: #word or #nested/path. Cannot be preceded by alphanumeric or '_'
# (to skip color codes, URL fragments, issue refs). Allows letters, digits,
# underscore, hyphen, forward slash for nesting.
_TAG_RE = re.compile(
    r"(?<![0-9A-Za-z_/])#(?P<tag>[A-Za-z_][\w\-/]*)"
)

# Markdown inline links [text](url). Not reference-style ([text][ref]).
# Allows parens inside the URL via a simple balanced-ish pattern.
_MD_LINK_RE = re.compile(
    r"(?<!!)\[(?P<text>[^\[\]\n]+)\]\((?P<url>[^\s\)]+(?:\s+\"[^\"]*\")?)\)"
)


def _strip_code(text: str) -> str:
    """Remove fenced and inline code — they should not contribute links."""
    text = _FENCED_CODE_RE.sub("", text)
    text = _INLINE_CODE_RE.sub("", text)
    return text


def extract_links(body: str) -> NoteLinks:
    """Extract wikilinks, tags, and markdown links from note body text.

    Code blocks and inline code are stripped before extraction. Order is
    preserved on first occurrence; duplicates are removed.
    """
    stripped = _strip_code(body)

    seen_wl: set[str] = set()
    wikilinks: list[Wikilink] = []
    for m in _WIKILINK_RE.finditer(stripped):
        target = m.group("target").strip()
        heading = (m.group("heading") or "").strip() or None
        alias = (m.group("alias") or "").strip() or None
        is_embed = m.group("embed") == "!"
        key = f"{int(is_embed)}|{target}|{heading or ''}|{alias or ''}"
        if key in seen_wl:
            continue
        seen_wl.add(key)
        wikilinks.append(
            Wikilink(
                target=target,
                heading=heading,
                alias=alias,
                is_embed=is_embed,
                raw=m.group(0),
            )
        )

    seen_tags: set[str] = set()
    tags: list[str] = []
    for m in _TAG_RE.finditer(stripped):
        t = m.group("tag")
        if t in seen_tags:
            continue
        seen_tags.add(t)
        tags.append(t)

    seen_md: set[tuple[str, str]] = set()
    md_links: list[tuple[str, str]] = []
    for m in _MD_LINK_RE.finditer(stripped):
        pair = (m.group("text").strip(), m.group("url").strip())
        if pair in seen_md:
            continue
        seen_md.add(pair)
        md_links.append(pair)

    return NoteLinks(
        wikilinks=tuple(wikilinks),
        tags=tuple(tags),
        markdown_links=tuple(md_links),
    )
