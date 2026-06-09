"""Temporal Drift Detector — git walker + claim extractor + aligner + filters (P8).

Pipeline:
  1. resolve_git_root()        — locate the .git directory from any vault sub-path.
  2. walk_note_revisions()     — shell git log to get ordered Revision list per note.
  3. fetch_revision_content()  — shell git show to retrieve a note at a specific SHA.
  4. extract_claims()          — strip frontmatter/headings/fences → sentence list.
  5. align_claims()            — BGE cosine matrix; classify into identical/candidate/unaligned.
  6. filter_pairs()            — three deterministic noise filters.
  7. build_candidate_pairs()   — walk adjacent revisions, return CandidatePair list.

The drift judge lives in drift_judge.py; formatting in drift_format.py.
This module owns no LLM and no network calls.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

import numpy as np


class _Embedder(Protocol):
    """Minimal embedder interface used by the aligner.

    Matches the public shape of ``BGEEmbedder.encode_passages`` without
    forcing an import of the concrete class here (avoids circular imports
    and keeps the module model-free).
    """

    def encode_passages(self, passages: list[str]):  # type: ignore[no-untyped-def]
        ...

DriftType = Literal["reversal", "refinement", "scope_change", "none"]

DEFAULT_ALIGN_THRESHOLD: float = 0.75
DEFAULT_IDENTICAL_THRESHOLD: float = 0.98


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class GitError(RuntimeError):
    """Raised when a git subprocess call fails."""


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Revision:
    """One historical version of a note."""

    sha: str
    timestamp: int  # unix epoch, from git %ct
    rel_path: str   # path relative to repo root, forward slashes
    content: str    # raw markdown text at this revision


@dataclass(frozen=True)
class CandidatePair:
    """A before/after sentence pair from adjacent revisions of the same note.

    Both sentences passed the alignment threshold filter but are not identical
    (cosine < identical_threshold), so the judge should evaluate them.
    """

    note_rel: str       # note path relative to repo root
    before: Revision
    after: Revision
    before_claim: str
    after_claim: str
    cosine: float


@dataclass(frozen=True)
class DriftEvent:
    """A confirmed drift event returned by the judge."""

    note_rel: str
    before: Revision
    after: Revision
    before_claim: str
    after_claim: str
    drift_type: DriftType
    score: int          # 1-5
    reasoning: str


@dataclass
class DriftReport:
    """Aggregated result of a full drift-detection run."""

    vault: str
    repo_root: str
    walked_commits: int = 0
    pairs_considered: int = 0
    pairs_filtered: int = 0
    pairs_judged: int = 0
    findings: list[DriftEvent] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------


def _run_git(repo_root: Path, args: list[str], *, check: bool = True) -> str:
    """Run a git command inside repo_root and return stdout as a string.

    Raises GitError on non-zero exit (when check=True) or if repo_root is
    not an existing directory (prevents the subprocess from inheriting an
    ambiguous cwd).
    """
    if not repo_root.is_dir():
        raise GitError(f"repo_root is not a directory: {repo_root}")
    cmd = ["git", "-C", str(repo_root)] + args
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=check,
        )
    except FileNotFoundError as exc:
        raise GitError("git executable not found on PATH") from exc
    except subprocess.CalledProcessError as exc:
        raise GitError(
            f"git {args[0]!r} failed (exit {exc.returncode}): {exc.stderr.strip()}"
        ) from exc
    return result.stdout


def resolve_git_root(vault_path: Path) -> Path:
    """Return the git repository root that contains vault_path.

    vault_path may be the repo root itself or any sub-directory.
    Raises GitError if vault_path is not inside a git repository.
    """
    vault_path = vault_path.resolve()
    if not vault_path.exists():
        raise GitError(f"vault path does not exist: {vault_path}")

    # Walk up to find a directory that is inside a git repo.
    search = vault_path if vault_path.is_dir() else vault_path.parent
    try:
        raw = _run_git(search, ["rev-parse", "--show-toplevel"])
    except GitError as exc:
        raise GitError(
            f"{vault_path} is not inside a git repository: {exc}"
        ) from exc

    root = Path(raw.strip())
    return root


def _validate_rel_path(repo_root: Path, rel: str) -> None:
    """Raise GitError if rel escapes the repo root (path-traversal guard)."""
    resolved = (repo_root / rel).resolve()
    try:
        resolved.relative_to(repo_root.resolve())
    except ValueError as exc:
        raise GitError(f"path {rel!r} escapes the repository root") from exc


def walk_note_revisions(repo_root: Path, rel_path: str) -> list[Revision]:
    """Return all revisions of rel_path in chronological (oldest-first) order.

    Uses ``git log --follow`` so simple renames are tracked.
    Each Revision has the SHA, unix timestamp, and the note's content at that SHA.
    Returns an empty list if the path has no commits (new untracked file).
    """
    _validate_rel_path(repo_root, rel_path)

    # %H = full SHA, %ct = committer unix timestamp; NUL-separated to avoid
    # collisions with whitespace in commit messages.
    raw = _run_git(
        repo_root,
        [
            "log",
            "--follow",
            "--first-parent",
            "--format=%H%x00%ct",
            "-M",
            "--",
            rel_path,
        ],
    )

    revisions: list[Revision] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("\x00")
        if len(parts) != 2:
            continue
        sha, ts_str = parts
        try:
            ts = int(ts_str)
        except ValueError:
            continue
        content = fetch_revision_content(repo_root, sha, rel_path)
        revisions.append(Revision(sha=sha, timestamp=ts, rel_path=rel_path, content=content))

    # git log returns newest-first; reverse to chronological order.
    revisions.reverse()
    return revisions


def fetch_revision_content(repo_root: Path, sha: str, rel_path: str) -> str:
    """Return the text content of rel_path at the given SHA.

    Raises GitError on any git failure (SHA not found, path not in tree, etc.).
    Path-traversal guard applied before calling git.
    """
    _validate_rel_path(repo_root, rel_path)
    # Validate sha is a plausible hex string to prevent shell injection,
    # even though shell=False makes injection impossible anyway.
    if not re.fullmatch(r"[0-9a-fA-F]{4,64}", sha):
        raise GitError(f"invalid SHA: {sha!r}")
    return _run_git(repo_root, ["show", f"{sha}:{rel_path}"])


# ---------------------------------------------------------------------------
# Claim extraction
# ---------------------------------------------------------------------------

# Abbreviations that end with a period but do NOT end a sentence.
_ABBREVS: frozenset[str] = frozenset(
    [
        "dr", "mr", "mrs", "ms", "prof", "sr", "jr", "vs", "etc",
        "e.g", "i.e", "fig", "st", "ave", "approx", "vol", "no",
        "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep",
        "oct", "nov", "dec",
    ]
)

_FENCE_RE = re.compile(r"^```.*?^```", re.MULTILINE | re.DOTALL)
_HEADING_RE = re.compile(r"^#{1,6}\s+.*$", re.MULTILINE)

# Size guard on note content — a single note larger than this is treated
# as out-of-scope for drift detection. Prevents pathological regex work
# and keeps the embedder's batch size predictable.
_MAX_NOTE_BYTES = 1_000_000  # 1 MB
_WIKILINK_RE = re.compile(r"!\[\[.*?\]\]|\[\[.*?\]\]")
_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_INLINE_CODE_RE = re.compile(r"`[^`]+`")
_TABLE_ROW_RE = re.compile(r"^\|.*\|$", re.MULTILINE)


def extract_claims(content: str, granularity: str = "sentence") -> list[str]:
    """Strip structural markdown and return a list of claim strings.

    granularity:
        "sentence" — split into individual sentences (default).
        "paragraph" — blank-line-separated blocks.

    Returns an empty list if the note has no prose after stripping, or if
    the note exceeds _MAX_NOTE_BYTES (treated as out-of-scope rather than
    raising, so a single giant note does not abort a whole drift run).
    """
    if len(content.encode("utf-8", errors="replace")) > _MAX_NOTE_BYTES:
        return []
    text = content

    # Strip YAML frontmatter (line-scanner, not regex — avoids G3 catastrophic backtracking).
    lines = text.split("\n")
    if lines and lines[0].strip() == "---":
        end = None
        for i, ln in enumerate(lines[1:], 1):
            if ln.strip() == "---":
                end = i
                break
        if end is not None:
            lines = lines[end + 1:]
    text = "\n".join(lines)

    # Strip fenced code blocks.
    text = _FENCE_RE.sub("", text)
    # Strip headings.
    text = _HEADING_RE.sub("", text)
    # Strip table rows.
    text = _TABLE_ROW_RE.sub("", text)
    # Strip wikilinks — keep display text for [[alias|display]] form, else nothing.
    text = _WIKILINK_RE.sub("", text)
    # Strip markdown links — keep link text.
    text = _MD_LINK_RE.sub(r"\1", text)
    # Strip inline code.
    text = _INLINE_CODE_RE.sub("", text)
    # Collapse multiple blank lines.
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()

    if not text:
        return []

    if granularity == "paragraph":
        return [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]

    # Sentence splitting.
    return _split_sentences(text)


def _split_sentences(text: str) -> list[str]:
    """Rule-based sentence splitter. Handles common abbreviations."""
    # Normalise whitespace within the text (keep sentence boundaries).
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n+", " ", text)

    # Split on ". " / "? " / "! " followed by uppercase, but protect abbreviations.
    tokens = re.split(r"(?<=[.?!])\s+(?=[A-Z\"])", text)

    sentences: list[str] = []
    buffer = ""
    for tok in tokens:
        candidate = buffer + " " + tok if buffer else tok

        # Check whether the split happened after an abbreviation.
        # "Dr. Smith" → last word of buffer is an abbreviation.
        words_so_far = buffer.rstrip(".").split()
        last_word = words_so_far[-1].lower().rstrip(".") if words_so_far else ""
        if last_word in _ABBREVS and buffer:
            buffer = candidate
        else:
            if buffer:
                sentences.append(buffer.strip())
            buffer = tok

    if buffer:
        sentences.append(buffer.strip())

    return [s for s in sentences if len(s) > 10]


# ---------------------------------------------------------------------------
# Alignment
# ---------------------------------------------------------------------------


def align_claims(
    before_claims: list[str],
    after_claims: list[str],
    embedder: _Embedder,
    align_threshold: float = DEFAULT_ALIGN_THRESHOLD,
    identical_threshold: float = DEFAULT_IDENTICAL_THRESHOLD,
) -> list[tuple[str, str, float]]:
    """Return (before_claim, after_claim, cosine) triples in [align, identical) range.

    For each before_claim, finds its best-matching after_claim by cosine.
    Pairs outside the window are dropped (too dissimilar or too identical).
    """
    if not before_claims or not after_claims:
        return []

    before_embs = embedder.encode_passages(before_claims)
    after_embs = embedder.encode_passages(after_claims)

    # Normalise for cosine.
    before_norm = before_embs / (np.linalg.norm(before_embs, axis=1, keepdims=True) + 1e-9)
    after_norm = after_embs / (np.linalg.norm(after_embs, axis=1, keepdims=True) + 1e-9)

    sim = before_norm @ after_norm.T  # shape: (len_before, len_after)

    pairs: list[tuple[str, str, float]] = []
    for i, bc in enumerate(before_claims):
        best_j = int(np.argmax(sim[i]))
        cosine = float(sim[i, best_j])
        if align_threshold <= cosine < identical_threshold:
            pairs.append((bc, after_claims[best_j], cosine))

    return pairs


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------


def _normalise(text: str) -> str:
    """Lowercase, collapse whitespace, strip punctuation for comparison."""
    text = text.lower()
    text = re.sub(r"[^\w\s]", "", text)
    return re.sub(r"\s+", " ", text).strip()


_LEVENSHTEIN_MAX_LEN = 1000


def _levenshtein(a: str, b: str) -> int:
    """Pure-Python Levenshtein distance.

    Returns a large sentinel (> any realistic threshold) when either input
    exceeds _LEVENSHTEIN_MAX_LEN chars. This bounds the O(n*m) worst case
    on adversarial input (a note with a very long sentence) without
    crashing: the filter downstream will simply keep the pair for the
    judge to decide, which is the safe failure mode.
    """
    if a == b:
        return 0
    if len(a) > _LEVENSHTEIN_MAX_LEN or len(b) > _LEVENSHTEIN_MAX_LEN:
        return _LEVENSHTEIN_MAX_LEN  # sentinel: definitely above any typo threshold
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for ch_a in a:
        curr = [prev[0] + 1]
        for j, ch_b in enumerate(b):
            curr.append(min(curr[-1] + 1, prev[j + 1] + 1, prev[j] + (ch_a != ch_b)))
        prev = curr
    return prev[-1]


def filter_candidate_pairs(
    pairs: list[tuple[str, str, float]],
) -> list[tuple[str, str, float]]:
    """Apply three deterministic noise filters to raw aligned pairs.

    Filters (each drops a pair):
    1. Whitespace-only diff — normalised texts are equal.
    2. List-reorder — multiset of tokens is equal.
    3. Proper-name typo — Levenshtein < 3 after normalisation.

    Returns the pairs that pass all three filters.
    """
    kept: list[tuple[str, str, float]] = []
    for before, after, cosine in pairs:
        nb = _normalise(before)
        na = _normalise(after)

        # Filter 1: whitespace/punctuation-only diff.
        if nb == na:
            continue

        # Filter 2: list reorder (multiset equality).
        if sorted(nb.split()) == sorted(na.split()):
            continue

        # Filter 3: near-identical after normalisation (typo / proper-name fix).
        if _levenshtein(nb, na) < 3:
            continue

        kept.append((before, after, cosine))
    return kept


# ---------------------------------------------------------------------------
# Pair builder
# ---------------------------------------------------------------------------


def build_candidate_pairs(
    revisions: list[Revision],
    embedder: _Embedder,
    align_threshold: float = DEFAULT_ALIGN_THRESHOLD,
    identical_threshold: float = DEFAULT_IDENTICAL_THRESHOLD,
    granularity: str = "sentence",
) -> list[CandidatePair]:
    """Walk adjacent revision pairs for a note and return filtered CandidatePairs."""
    if len(revisions) < 2:
        return []

    result: list[CandidatePair] = []
    for prev_rev, next_rev in zip(revisions, revisions[1:], strict=False):
        before_claims = extract_claims(prev_rev.content, granularity)
        after_claims = extract_claims(next_rev.content, granularity)

        raw_pairs = align_claims(
            before_claims, after_claims, embedder,
            align_threshold=align_threshold,
            identical_threshold=identical_threshold,
        )
        filtered = filter_candidate_pairs(raw_pairs)

        for bc, ac, cosine in filtered:
            result.append(
                CandidatePair(
                    note_rel=prev_rev.rel_path,
                    before=prev_rev,
                    after=next_rev,
                    before_claim=bc,
                    after_claim=ac,
                    cosine=cosine,
                )
            )
    return result
