"""Tests for the git walker portion of the Temporal Drift Detector (P8.1).

All tests use pytest's tmp_path fixture to create throwaway git repos —
no dependency on fixtures/drift_vault/ (which ships in Phase 8.5).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from wikilens.drift import (
    GitError,
    Revision,
    extract_claims,
    fetch_revision_content,
    filter_candidate_pairs,
    resolve_git_root,
    walk_note_revisions,
    _normalise,
    _levenshtein,
    _split_sentences,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo)] + list(args),
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _init_repo(path: Path) -> Path:
    """Create a minimal git repo at path and return it."""
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test")
    return path


def _commit(repo: Path, rel: str, content: str, msg: str = "commit") -> str:
    """Write content to rel inside repo, stage, and commit. Returns SHA."""
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    _git(repo, "add", rel)
    _git(repo, "commit", "-m", msg)
    return _git(repo, "rev-parse", "HEAD")


# ---------------------------------------------------------------------------
# resolve_git_root
# ---------------------------------------------------------------------------


def test_resolve_git_root_vault_equals_root(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    _commit(repo, "note.md", "hello")
    assert resolve_git_root(repo) == repo


def test_resolve_git_root_vault_is_subdir(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    _commit(repo, "notes/a.md", "hello")
    subdir = repo / "notes"
    assert resolve_git_root(subdir) == repo


def test_resolve_git_root_outside_repo(tmp_path):
    plain = tmp_path / "notarepo"
    plain.mkdir()
    with pytest.raises(GitError, match="not inside a git repository"):
        resolve_git_root(plain)


def test_resolve_git_root_nonexistent_path(tmp_path):
    with pytest.raises(GitError, match="does not exist"):
        resolve_git_root(tmp_path / "ghost")


# ---------------------------------------------------------------------------
# walk_note_revisions
# ---------------------------------------------------------------------------


def test_walk_note_revisions_returns_chronological_order(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    sha1 = _commit(repo, "notes/chem.md", "Water boils at 100C.", "v1")
    sha2 = _commit(repo, "notes/chem.md", "Water boils at 100C at sea level.", "v2")
    sha3 = _commit(repo, "notes/chem.md", "Boiling point varies with pressure.", "v3")

    revs = walk_note_revisions(repo, "notes/chem.md")
    assert len(revs) == 3
    assert [r.sha for r in revs] == [sha1, sha2, sha3]


def test_walk_note_revisions_content_matches_commit(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    _commit(repo, "note.md", "First version.", "v1")
    _commit(repo, "note.md", "Second version.", "v2")

    revs = walk_note_revisions(repo, "note.md")
    assert revs[0].content == "First version."
    assert revs[1].content == "Second version."


def test_walk_note_revisions_untracked_returns_empty(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    _commit(repo, "other.md", "unrelated")
    revs = walk_note_revisions(repo, "notes/nonexistent.md")
    assert revs == []


def test_walk_note_revisions_single_commit(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    sha = _commit(repo, "a.md", "Only version.")
    revs = walk_note_revisions(repo, "a.md")
    assert len(revs) == 1
    assert revs[0].sha == sha


def test_walk_note_revisions_unrelated_commits_excluded(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    sha1 = _commit(repo, "a.md", "Version 1.", "v1")
    _commit(repo, "b.md", "Unrelated note.", "other")
    sha2 = _commit(repo, "a.md", "Version 2.", "v2")

    revs = walk_note_revisions(repo, "a.md")
    assert len(revs) == 2
    assert revs[0].sha == sha1
    assert revs[1].sha == sha2


# ---------------------------------------------------------------------------
# fetch_revision_content
# ---------------------------------------------------------------------------


def test_fetch_revision_content_returns_exact_text(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    sha = _commit(repo, "note.md", "Exact content here.")
    content = fetch_revision_content(repo, sha, "note.md")
    assert content == "Exact content here."


def test_fetch_revision_content_bad_sha_raises(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    _commit(repo, "note.md", "hello")
    with pytest.raises(GitError):
        fetch_revision_content(repo, "deadbeef" * 5, "note.md")


def test_fetch_revision_content_path_traversal_raises(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    sha = _commit(repo, "note.md", "hello")
    with pytest.raises(GitError, match="escapes"):
        fetch_revision_content(repo, sha, "../outside.txt")


def test_fetch_revision_content_invalid_sha_format_raises(tmp_path):
    repo = _init_repo(tmp_path / "repo")
    _commit(repo, "note.md", "hello")
    with pytest.raises(GitError, match="invalid SHA"):
        fetch_revision_content(repo, "not-a-sha!", "note.md")


# ---------------------------------------------------------------------------
# extract_claims
# ---------------------------------------------------------------------------


def test_extract_claims_strips_frontmatter():
    md = "---\ntitle: Test\ntags: [a, b]\n---\n\nThe sky is blue. Water is wet."
    claims = extract_claims(md)
    assert all("title" not in c and "tags" not in c for c in claims)
    assert any("sky" in c for c in claims)


def test_extract_claims_strips_fenced_code():
    md = "Some prose.\n\n```python\nx = 1\n```\n\nMore prose."
    claims = extract_claims(md)
    assert not any("x = 1" in c for c in claims)
    assert any("prose" in c for c in claims)


def test_extract_claims_strips_headings():
    md = "# Big heading\n\nThe claim is here.\n\n## Sub\n\nAnother claim."
    claims = extract_claims(md)
    assert not any(c.startswith("#") for c in claims)
    assert any("claim" in c for c in claims)


def test_extract_claims_strips_wikilinks():
    md = "This note references [[chemistry]] and [[physics|Physics]]."
    claims = extract_claims(md)
    assert not any("[[" in c for c in claims)


def test_extract_claims_keeps_link_text():
    md = "See [the paper](https://example.com) for details."
    claims = extract_claims(md)
    assert any("the paper" in c for c in claims)


def test_extract_claims_paragraph_granularity():
    md = "First paragraph claim.\n\nSecond paragraph claim.\n\nThird."
    claims = extract_claims(md, granularity="paragraph")
    assert len(claims) == 3


def test_extract_claims_empty_note_returns_empty():
    assert extract_claims("") == []
    assert extract_claims("---\ntitle: x\n---\n") == []


def test_extract_claims_code_only_returns_empty():
    md = "```python\nprint('hello')\n```\n"
    claims = extract_claims(md)
    assert claims == []


# ---------------------------------------------------------------------------
# _split_sentences
# ---------------------------------------------------------------------------


def test_split_sentences_basic():
    text = "The sky is blue. Water is wet. Fire is hot."
    sentences = _split_sentences(text)
    assert len(sentences) == 3


def test_split_sentences_protects_dr_abbreviation():
    text = "Dr. Smith published the finding. It was correct."
    sentences = _split_sentences(text)
    assert len(sentences) == 2
    assert "Dr. Smith" in sentences[0]


def test_split_sentences_question_and_exclamation():
    text = "Is water wet? Yes, it is! And the sky is blue."
    sentences = _split_sentences(text)
    assert len(sentences) == 3


def test_split_sentences_short_fragments_dropped():
    # Fragments under 10 chars are dropped.
    text = "OK. The real claim is here and is long enough."
    sentences = _split_sentences(text)
    assert not any(len(s) <= 10 for s in sentences)


# ---------------------------------------------------------------------------
# _normalise and _levenshtein helpers
# ---------------------------------------------------------------------------


def test_normalise_strips_punctuation_and_lowercases():
    assert _normalise("Hello, World!") == "hello world"


def test_levenshtein_identical():
    assert _levenshtein("abc", "abc") == 0


def test_levenshtein_single_substitution():
    assert _levenshtein("abc", "axc") == 1


def test_levenshtein_insertion():
    assert _levenshtein("ab", "abc") == 1


def test_levenshtein_deletion():
    assert _levenshtein("abc", "ac") == 1


# ---------------------------------------------------------------------------
# filter_candidate_pairs
# ---------------------------------------------------------------------------


def test_filter_drops_whitespace_only_diff():
    # After normalisation these are identical.
    pairs = [("Hello, world!", "Hello world", 0.85)]
    assert filter_candidate_pairs(pairs) == []


def test_filter_drops_list_reorder():
    pairs = [("A, B, C are key.", "C, B, A are key.", 0.88)]
    assert filter_candidate_pairs(pairs) == []


def test_filter_drops_typo_fix():
    # "Einstien" → "Einstein" is Levenshtein 2 — should be dropped.
    pairs = [("Einstien developed relativity.", "Einstein developed relativity.", 0.90)]
    assert filter_candidate_pairs(pairs) == []


def test_filter_keeps_genuine_drift():
    pairs = [
        (
            "Water boils at 100C at all altitudes.",
            "Water boils at 100C only at sea level; boiling point drops with altitude.",
            0.82,
        )
    ]
    result = filter_candidate_pairs(pairs)
    assert len(result) == 1
    assert result[0][2] == pytest.approx(0.82)


def test_filter_keeps_multiple_genuine_pairs():
    pairs = [
        ("Meditation is proven to reduce anxiety.", "Some studies suggest meditation may help with anxiety.", 0.80),
        ("We should use Postgres.", "We should use SQLite for this project.", 0.78),
    ]
    result = filter_candidate_pairs(pairs)
    assert len(result) == 2


def test_filter_mixed_keeps_only_genuine():
    pairs = [
        ("Dr. Smith published this.", "Dr. Smith published that.", 0.91),  # typo-level, should drop
        ("AI will replace all coders.", "AI will automate routine coding tasks, not replace all coders.", 0.79),  # genuine
    ]
    result = filter_candidate_pairs(pairs)
    # The first pair normalises to very short edit distance; the second should pass.
    genuine = [p for p in result if "automate" in p[1]]
    assert len(genuine) == 1
