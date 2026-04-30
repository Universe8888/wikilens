"""Vault ingestion primitives.

Grows across P2 steps 2-5:
  - step 2: vault walker
  - step 3: frontmatter parser
  - step 4: wikilink / tag / embed extractor
  - step 5: heading-aware chunker (this commit)
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import tiktoken
import yaml

DEFAULT_INCLUDE: tuple[str, ...] = ("**/*.md",)
DEFAULT_EXCLUDE: tuple[str, ...] = ()


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


@dataclass(frozen=True)
class Chunk:
    """A retrievable unit of note text with full provenance metadata.

    Deterministic `chunk_id` lets re-ingestion replace existing rows in
    place (supports incremental indexing in P3).
    """

    chunk_id: str
    source_path: Path
    source_rel: str
    heading_path: tuple[str, ...]
    text: str
    token_count: int
    char_start: int
    char_end: int
    chunk_index: int
    content_hash: str
    frontmatter: dict[str, Any] = field(default_factory=dict)


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


def _is_fence_line(line: str) -> bool:
    """A frontmatter fence line is `---` optionally followed by spaces/tabs."""
    stripped = line.rstrip("\r\n")
    if not stripped.startswith("---"):
        return False
    # Everything after the three dashes must be whitespace only.
    return stripped[3:].strip(" \t") == ""


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str, str | None]:
    """Split raw note text into (frontmatter_dict, body, error).

    - No frontmatter fence → ({}, original_text, None)
    - Valid YAML mapping frontmatter → (dict, body_after_fence, None)
    - Empty frontmatter block (just `---\\n---`) → ({}, body, None)
    - Malformed YAML → ({}, body_after_fence, "<yaml error>")
    - Valid YAML but non-mapping (e.g. a scalar or list) → ({}, body_after_fence,
      "frontmatter is not a mapping")

    Implementation: a simple line-scanner (O(n), no backtracking). The prior
    regex-based version suffered catastrophic backtracking on files whose YAML
    block contained bracketed structures (G3).
    """
    if not text.startswith("---"):
        return {}, text, None

    lines = text.splitlines(keepends=True)
    if not lines or not _is_fence_line(lines[0]):
        return {}, text, None

    # Find the closing fence on its own line.
    close_idx: int | None = None
    for i in range(1, len(lines)):
        if _is_fence_line(lines[i]):
            close_idx = i
            break

    if close_idx is None:
        # Unterminated frontmatter → treat the whole thing as body, no error.
        return {}, text, None

    fm_text = "".join(lines[1:close_idx])
    body = "".join(lines[close_idx + 1 :])

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


# --- chunking -------------------------------------------------------------

DEFAULT_CHUNK_TOKENS = 400
DEFAULT_OVERLAP_RATIO = 0.15
MIN_CHUNK_TOKENS = 32  # don't emit tiny trailing chunks; merge upward instead

# cl100k_base is OpenAI's tokenizer, also a close approximation to the
# BGE/BERT WordPiece count (within ~10%). Used here only for budget math.
_ENCODER = tiktoken.get_encoding("cl100k_base")

# Match ATX headings (# Heading) up to H3. We intentionally ignore H4-H6
# as section boundaries — they usually mark sub-sub-detail within a topic
# and breaking on them fragments semantic units too aggressively.
_HEADING_RE = re.compile(r"^(?P<hashes>#{1,3})[ \t]+(?P<title>.+?)[ \t]*#*[ \t]*$", re.MULTILINE)


def _count_tokens(text: str) -> int:
    return len(_ENCODER.encode(text, disallowed_special=()))


def _split_sections(body: str) -> list[tuple[tuple[str, ...], str, int]]:
    """Split body on H1/H2/H3 headings.

    Returns list of (heading_path, section_text, char_offset_of_section_in_body).
    If the body has no headings, returns a single section with heading_path=().

    Heading hierarchy is tracked: an H2 nested under an H1 will have
    heading_path = ("H1 title", "H2 title").
    """
    matches = list(_HEADING_RE.finditer(body))
    if not matches:
        return [((), body, 0)]

    sections: list[tuple[tuple[str, ...], str, int]] = []
    stack: list[str] = []  # heading titles by level (index 0 = H1, 1 = H2, ...)
    cursor_level: list[int] = []  # parallel to stack, storing the level number

    # Preamble before the first heading (if any)
    if matches[0].start() > 0:
        preamble = body[: matches[0].start()]
        if preamble.strip():
            sections.append(((), preamble, 0))

    for i, m in enumerate(matches):
        level = len(m.group("hashes"))
        title = m.group("title").strip()

        # Pop stack entries at this level or deeper
        while cursor_level and cursor_level[-1] >= level:
            stack.pop()
            cursor_level.pop()
        stack.append(title)
        cursor_level.append(level)

        section_start = m.end()
        # Skip the trailing newline after the heading line itself
        if section_start < len(body) and body[section_start] == "\n":
            section_start += 1

        section_end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        section_text = body[section_start:section_end]

        if section_text.strip():
            sections.append((tuple(stack), section_text, section_start))

    return sections


_PARAGRAPH_SPLIT_RE = re.compile(r"\n[ \t]*\n+")


def _split_paragraphs(text: str) -> list[tuple[str, int]]:
    """Split text into paragraphs, returning (paragraph, char_offset_in_text)."""
    paragraphs: list[tuple[str, int]] = []
    cursor = 0
    for m in _PARAGRAPH_SPLIT_RE.finditer(text):
        para = text[cursor : m.start()]
        if para.strip():
            paragraphs.append((para, cursor))
        cursor = m.end()
    tail = text[cursor:]
    if tail.strip():
        paragraphs.append((tail, cursor))
    return paragraphs


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'\(\[])")


def _split_sentences(para: str) -> list[str]:
    """Split a paragraph into sentences by a simple heuristic.

    Not perfect (won't handle 'Dr. Smith' well), but sufficient as a fallback
    for paragraphs that exceed the token budget on their own. For chunking
    purposes the boundary just needs to be deterministic and near-complete.
    """
    parts = _SENTENCE_SPLIT_RE.split(para)
    return [p for p in parts if p.strip()]


def _emit_chunks_from_section(
    section_text: str,
    heading_path: tuple[str, ...],
    section_offset_in_body: int,
    target_tokens: int,
    overlap_ratio: float,
) -> list[tuple[str, tuple[str, ...], int, int, int]]:
    """Produce list of (text, heading_path, char_start_in_body, char_end_in_body, token_count)
    for a single section. Overlap applied only within this section.
    """
    paragraphs = _split_paragraphs(section_text)
    if not paragraphs:
        return []

    overlap_tokens = max(1, int(target_tokens * overlap_ratio))

    # Pre-expand any single paragraph that itself exceeds the budget.
    expanded: list[tuple[str, int, int]] = []  # (text, offset_in_section, token_count)
    for para, off in paragraphs:
        tok = _count_tokens(para)
        if tok <= target_tokens:
            expanded.append((para, off, tok))
        else:
            # Fall back to sentence splitting for oversize paragraphs.
            sub_cursor = 0
            for sent in _split_sentences(para):
                sent_off = para.find(sent, sub_cursor)
                if sent_off < 0:
                    sent_off = sub_cursor
                expanded.append((sent, off + sent_off, _count_tokens(sent)))
                sub_cursor = sent_off + len(sent)

    chunks: list[tuple[str, tuple[str, ...], int, int, int]] = []
    buf: list[tuple[str, int, int]] = []
    buf_tokens = 0

    def flush():
        nonlocal buf, buf_tokens
        if not buf:
            return
        text = "\n\n".join(p[0] for p in buf).strip()
        first_off = buf[0][1]
        last_off_end = buf[-1][1] + len(buf[-1][0])
        char_start = section_offset_in_body + first_off
        char_end = section_offset_in_body + last_off_end
        chunks.append((text, heading_path, char_start, char_end, buf_tokens))
        buf = []
        buf_tokens = 0

    for text, off, tok in expanded:
        if buf_tokens + tok > target_tokens and buf_tokens >= MIN_CHUNK_TOKENS:
            flush()
            # Seed next buffer with overlap from the end of the previous chunk
            # (reusing the last paragraph(s) while under overlap budget).
            if chunks and overlap_tokens > 0:
                # Take trailing sentences from the previous chunk up to
                # overlap_tokens. If a single sentence is already larger than
                # the overlap budget, skip overlap entirely — a truthful
                # overlap is not possible and doubling the content would
                # blow the token budget.
                prev_text = chunks[-1][0]
                prev_sentences = _split_sentences(prev_text)
                carry: list[str] = []
                carry_tokens = 0
                for s in reversed(prev_sentences):
                    s_tok = _count_tokens(s)
                    if carry_tokens + s_tok > overlap_tokens:
                        break
                    carry.insert(0, s)
                    carry_tokens += s_tok
                if carry:
                    carry_text = " ".join(carry)
                    buf.append((carry_text, off, carry_tokens))
                    buf_tokens = carry_tokens
        buf.append((text, off, tok))
        buf_tokens += tok

    flush()
    return chunks


def chunk_note(
    note: Note,
    vault_root: str | Path | None = None,
    target_tokens: int = DEFAULT_CHUNK_TOKENS,
    overlap_ratio: float = DEFAULT_OVERLAP_RATIO,
) -> list[Chunk]:
    """Split a parsed note into retrievable chunks with full metadata.

    - Heading-aware: H1/H2/H3 boundaries are respected; overlap never
      crosses a section boundary (research: section boundaries are the
      strongest available semantic signal in markdown).
    - Oversized paragraphs are sentence-split as a fallback.
    - Chunks below MIN_CHUNK_TOKENS merge into the next chunk when possible.

    If `vault_root` is given, `source_rel` uses that as the base; otherwise
    the rel path falls back to the note's file name.
    """
    body = note.body
    if not body.strip():
        return []

    if vault_root is not None:
        try:
            rel = str(note.path.resolve().relative_to(Path(vault_root).resolve())).replace(
                "\\", "/"
            )
        except ValueError:
            rel = note.path.name
    else:
        rel = note.path.name

    sections = _split_sections(body)

    chunks: list[Chunk] = []
    idx = 0
    for heading_path, section_text, section_off in sections:
        for text, hp, c_start, c_end, tok in _emit_chunks_from_section(
            section_text,
            heading_path,
            section_off,
            target_tokens,
            overlap_ratio,
        ):
            content_hash = hashlib.sha1(
                text.encode("utf-8"), usedforsecurity=False
            ).hexdigest()[:16]
            chunk_id = hashlib.sha1(
                f"{rel}::{idx}".encode(), usedforsecurity=False
            ).hexdigest()[:16]
            chunks.append(
                Chunk(
                    chunk_id=chunk_id,
                    source_path=note.path,
                    source_rel=rel,
                    heading_path=hp,
                    text=text,
                    token_count=tok,
                    char_start=c_start,
                    char_end=c_end,
                    chunk_index=idx,
                    content_hash=content_hash,
                    frontmatter=note.frontmatter,
                )
            )
            idx += 1

    return chunks
