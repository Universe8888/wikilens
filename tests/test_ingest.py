"""Tests for vault ingestion primitives."""

from __future__ import annotations

from pathlib import Path

import pytest

from wikilens.ingest import (
    Note,
    extract_links,
    parse_frontmatter,
    parse_note,
    walk_vault,
)


def _make(root: Path, rel: str, body: str = "x") -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


def test_walk_finds_markdown_recursively(tmp_path: Path):
    _make(tmp_path, "a.md")
    _make(tmp_path, "sub/b.md")
    _make(tmp_path, "sub/deeper/c.md")
    _make(tmp_path, "notes.txt")  # not markdown

    result = walk_vault(tmp_path)

    names = [p.name for p in result]
    assert names == ["a.md", "b.md", "c.md"]
    assert all(p.is_absolute() for p in result)


def test_walk_output_is_sorted_deterministic(tmp_path: Path):
    for name in ["zebra.md", "apple.md", "mango.md"]:
        _make(tmp_path, name)

    first = walk_vault(tmp_path)
    second = walk_vault(tmp_path)

    assert first == second
    assert [p.name for p in first] == sorted(p.name for p in first)


def test_walk_honors_exclude(tmp_path: Path):
    _make(tmp_path, "keep.md")
    _make(tmp_path, "drafts/skip.md")
    _make(tmp_path, "drafts/nested/also-skip.md")

    result = walk_vault(tmp_path, exclude=["drafts/**/*.md"])

    assert [p.name for p in result] == ["keep.md"]


def test_walk_custom_include(tmp_path: Path):
    _make(tmp_path, "a.md")
    _make(tmp_path, "b.markdown")

    result = walk_vault(tmp_path, include=["**/*.markdown"])

    assert [p.name for p in result] == ["b.markdown"]


def test_walk_missing_root_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        walk_vault(tmp_path / "does-not-exist")


def test_walk_file_root_raises(tmp_path: Path):
    f = _make(tmp_path, "lonely.md")
    with pytest.raises(NotADirectoryError):
        walk_vault(f)


def test_walk_empty_vault(tmp_path: Path):
    assert walk_vault(tmp_path) == []


def test_walk_sample_vault_fixture():
    """Smoke test against the real in-repo fixture.

    P2 step 11 will populate this with synthetic notes; for now it just
    contains a README.md, which is also valid markdown the walker should find.
    """
    fixture = Path(__file__).parent.parent / "fixtures" / "sample_vault"
    result = walk_vault(fixture)
    assert len(result) >= 1
    assert any(p.name == "README.md" for p in result)


# --- frontmatter parser ---------------------------------------------------


def test_frontmatter_happy_path():
    text = "---\ntitle: Hello\ntags: [a, b]\n---\nbody line 1\nbody line 2\n"
    fm, body, err = parse_frontmatter(text)
    assert err is None
    assert fm == {"title": "Hello", "tags": ["a", "b"]}
    assert body == "body line 1\nbody line 2\n"


def test_frontmatter_absent_returns_original_text():
    text = "# Heading\n\nNo frontmatter here.\n"
    fm, body, err = parse_frontmatter(text)
    assert err is None
    assert fm == {}
    assert body == text


def test_frontmatter_empty_block():
    text = "---\n---\nbody\n"
    fm, body, err = parse_frontmatter(text)
    assert err is None
    assert fm == {}
    assert body == "body\n"


def test_frontmatter_crlf_line_endings():
    text = "---\r\ntitle: CR\r\n---\r\nbody\r\n"
    fm, body, err = parse_frontmatter(text)
    assert err is None
    assert fm == {"title": "CR"}
    assert body == "body\r\n"


def test_frontmatter_malformed_yaml_captured_as_error():
    text = "---\ntitle: [unclosed\n---\nbody\n"
    fm, body, err = parse_frontmatter(text)
    assert fm == {}
    assert body == "body\n"
    assert err is not None and "yaml error" in err


def test_frontmatter_non_mapping_captured_as_error():
    text = "---\n- just\n- a\n- list\n---\nbody\n"
    fm, body, err = parse_frontmatter(text)
    assert fm == {}
    assert body == "body\n"
    assert err == "frontmatter is not a mapping"


def test_frontmatter_only_no_body():
    text = "---\ntitle: only\n---\n"
    fm, body, err = parse_frontmatter(text)
    assert err is None
    assert fm == {"title": "only"}
    assert body == ""


def test_frontmatter_fence_must_be_at_start():
    text = "\n---\ntitle: offset\n---\nbody\n"  # leading blank line → not frontmatter
    fm, body, err = parse_frontmatter(text)
    assert err is None
    assert fm == {}
    assert body == text


def test_parse_note_utf8_bom(tmp_path: Path):
    p = tmp_path / "bom.md"
    p.write_bytes(b"\xef\xbb\xbf---\ntitle: BOM\n---\nhello\n")
    note = parse_note(p)
    assert isinstance(note, Note)
    assert note.frontmatter == {"title": "BOM"}
    assert note.body == "hello\n"
    assert note.frontmatter_error is None


def test_parse_note_no_frontmatter(tmp_path: Path):
    p = _make(tmp_path, "plain.md", "# Just markdown\n\ncontent\n")
    note = parse_note(p)
    assert note.frontmatter == {}
    assert note.body == "# Just markdown\n\ncontent\n"
    assert note.frontmatter_error is None


# --- link extractor -------------------------------------------------------


def test_extract_plain_wikilink():
    links = extract_links("See [[Photosynthesis]] for details.")
    assert len(links.wikilinks) == 1
    wl = links.wikilinks[0]
    assert wl.target == "Photosynthesis"
    assert wl.heading is None
    assert wl.alias is None
    assert wl.is_embed is False


def test_extract_wikilink_with_alias():
    links = extract_links("[[Photosynthesis|how plants eat]]")
    wl = links.wikilinks[0]
    assert wl.target == "Photosynthesis"
    assert wl.alias == "how plants eat"
    assert wl.heading is None


def test_extract_wikilink_with_heading():
    links = extract_links("[[Photosynthesis#Light Reactions]]")
    wl = links.wikilinks[0]
    assert wl.target == "Photosynthesis"
    assert wl.heading == "Light Reactions"
    assert wl.alias is None


def test_extract_wikilink_with_heading_and_alias():
    links = extract_links("[[Page#Section|Display]]")
    wl = links.wikilinks[0]
    assert wl.target == "Page"
    assert wl.heading == "Section"
    assert wl.alias == "Display"


def test_extract_embed_wikilink():
    links = extract_links("Here it is: ![[Diagram]]")
    wl = links.wikilinks[0]
    assert wl.target == "Diagram"
    assert wl.is_embed is True


def test_extract_tags_basic():
    links = extract_links("Tagged #concept and #nested/sub here.")
    assert links.tags == ("concept", "nested/sub")


def test_extract_tags_rejects_mid_word_hashes():
    # URL fragments (#section after a slash) and mid-identifier hashes
    # (abc#123) must NOT be tagged. Color codes like #ffcc00 that start a
    # token are tags by Obsidian's own rules — acceptable noise for RAG.
    text = "url: https://example.com/page#section id: abc#123 rev: v1#2"
    links = extract_links(text)
    assert links.tags == ()


def test_extract_tags_accept_leading_digit_rejected():
    # Obsidian convention: tags must start with a letter or underscore,
    # not a digit (to avoid confusion with issue numbers like #123).
    links = extract_links("See #123 issue and #real-tag.")
    assert links.tags == ("real-tag",)


def test_extract_ignores_content_in_code_fences():
    text = (
        "Before [[real-link]].\n"
        "```python\n"
        "# this is a comment, not a tag\n"
        "x = '[[not-a-link]]'\n"
        "```\n"
        "After #actual-tag."
    )
    links = extract_links(text)
    assert [wl.target for wl in links.wikilinks] == ["real-link"]
    assert links.tags == ("actual-tag",)


def test_extract_ignores_inline_code():
    text = "Use `[[example]]` syntax to create `#tags`. Real: [[actual]] and #real."
    links = extract_links(text)
    assert [wl.target for wl in links.wikilinks] == ["actual"]
    assert links.tags == ("real",)


def test_extract_markdown_links():
    text = "See [the docs](https://example.com/x) and [local](./foo.md)."
    links = extract_links(text)
    assert links.markdown_links == (
        ("the docs", "https://example.com/x"),
        ("local", "./foo.md"),
    )


def test_extract_markdown_link_ignores_image():
    text = "![alt](img.png) and [real](page.md)"
    links = extract_links(text)
    # ![alt](img.png) is an image, not a regular link — we only want the second.
    assert links.markdown_links == (("real", "page.md"),)


def test_extract_dedupes_preserving_first_occurrence():
    text = "[[A]] then [[B]] then [[A]] again. #t #t #x"
    links = extract_links(text)
    assert [wl.target for wl in links.wikilinks] == ["A", "B"]
    assert links.tags == ("t", "x")


def test_extract_mixed_realistic_note():
    text = (
        "---\ntitle: notes\n---\n"
        "# Topic\n\n"
        "Linked to [[Photosynthesis|plant eating]] and "
        "[[Calvin Cycle#Dark Reactions]].\n"
        "Embedded: ![[diagram.png]]\n"
        "Tagged #biology and #chem/organic.\n"
        "External: [MDN](https://developer.mozilla.org).\n"
        "```\n#not-a-tag and [[not-a-link]]\n```\n"
    )
    # We pass the whole file — links ignore frontmatter fences as literal text.
    # In practice callers pass body only (parse_note splits), but this proves
    # the extractor is robust even if fed the whole file.
    links = extract_links(text)
    targets = [wl.target for wl in links.wikilinks]
    assert "Photosynthesis" in targets
    assert "Calvin Cycle" in targets
    assert "diagram.png" in targets
    assert "not-a-link" not in targets
    assert "biology" in links.tags
    assert "chem/organic" in links.tags
    assert "not-a-tag" not in links.tags
    assert ("MDN", "https://developer.mozilla.org") in links.markdown_links
