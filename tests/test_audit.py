"""Tests for the link-audit graph builder (P3, phase 3.1).

Focus: node identity (C2), target resolution (C1), self-link drop (C6),
embed-as-link (C7), shadowed basenames, and determinism of the produced
graph. Detectors land in phase 3.2 and are tested separately.
"""

from __future__ import annotations

from pathlib import Path

from wikilens.audit import (
    audit_vault,
    build_link_graph,
    find_broken_links,
    find_one_way_links,
    find_orphans,
    find_shadowed_links,
)


def _write(root: Path, rel: str, body: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


def test_empty_vault_yields_empty_graph(tmp_path: Path):
    g = build_link_graph(tmp_path)
    assert g.nodes == frozenset()
    assert g.outbound == {}
    assert g.inbound == {}
    assert g.by_key == {}


def test_node_key_strips_md_and_uses_forward_slashes(tmp_path: Path):
    _write(tmp_path, "a.md", "hello")
    _write(tmp_path, "sub/b.md", "hello")

    g = build_link_graph(tmp_path)

    assert g.nodes == frozenset({"a", "sub/b"})


def test_simple_forward_link_resolves(tmp_path: Path):
    _write(tmp_path, "a.md", "see [[b]] for context")
    _write(tmp_path, "b.md", "nothing here")

    g = build_link_graph(tmp_path)

    outs = g.outbound["a"]
    assert len(outs) == 1
    assert outs[0].resolved_to == ("b",)
    assert outs[0].is_embed is False
    assert g.inbound["b"] == ("a",)
    assert g.inbound["a"] == ()


def test_broken_link_has_empty_resolved_to(tmp_path: Path):
    _write(tmp_path, "a.md", "points to [[nonexistent]]")

    g = build_link_graph(tmp_path)

    (link,) = g.outbound["a"]
    assert link.target_raw == "nonexistent"
    assert link.resolved_to == ()


def test_self_link_is_dropped(tmp_path: Path):
    _write(tmp_path, "a.md", "I reference [[a]] myself.")

    g = build_link_graph(tmp_path)

    assert g.outbound["a"] == ()
    assert g.inbound["a"] == ()


def test_embed_counts_as_link(tmp_path: Path):
    _write(tmp_path, "a.md", "![[b]]")
    _write(tmp_path, "b.md", ".")

    g = build_link_graph(tmp_path)

    (link,) = g.outbound["a"]
    assert link.is_embed is True
    assert link.resolved_to == ("b",)
    assert g.inbound["b"] == ("a",)


def test_case_insensitive_basename_resolution(tmp_path: Path):
    _write(tmp_path, "Photosynthesis.md", ".")
    _write(tmp_path, "a.md", "see [[photosynthesis]]")

    g = build_link_graph(tmp_path)

    (link,) = g.outbound["a"]
    assert link.resolved_to == ("Photosynthesis",)


def test_full_path_link_resolves(tmp_path: Path):
    _write(tmp_path, "notes/topic.md", ".")
    _write(tmp_path, "a.md", "see [[notes/topic]]")

    g = build_link_graph(tmp_path)

    (link,) = g.outbound["a"]
    assert link.resolved_to == ("notes/topic",)


def test_link_with_trailing_md_suffix_resolves(tmp_path: Path):
    _write(tmp_path, "b.md", ".")
    _write(tmp_path, "a.md", "see [[b.md]]")

    g = build_link_graph(tmp_path)

    (link,) = g.outbound["a"]
    assert link.resolved_to == ("b",)


def test_shadowed_basename_produces_multiple_hits(tmp_path: Path):
    _write(tmp_path, "x/ideas.md", ".")
    _write(tmp_path, "y/ideas.md", ".")
    _write(tmp_path, "a.md", "[[ideas]]")

    g = build_link_graph(tmp_path)

    (link,) = g.outbound["a"]
    assert set(link.resolved_to) == {"x/ideas", "y/ideas"}
    # Both shadowed targets record the inbound edge.
    assert g.inbound["x/ideas"] == ("a",)
    assert g.inbound["y/ideas"] == ("a",)


def test_heading_and_alias_do_not_affect_resolution(tmp_path: Path):
    _write(tmp_path, "b.md", ".")
    _write(tmp_path, "a.md", "[[b#section|pretty name]]")

    g = build_link_graph(tmp_path)

    (link,) = g.outbound["a"]
    assert link.resolved_to == ("b",)


def test_duplicate_links_are_deduplicated(tmp_path: Path):
    _write(tmp_path, "b.md", ".")
    _write(tmp_path, "a.md", "first [[b]] and again [[b]] and [[b]]")

    g = build_link_graph(tmp_path)

    assert len(g.outbound["a"]) == 1


def test_links_in_code_blocks_are_ignored(tmp_path: Path):
    _write(
        tmp_path,
        "a.md",
        "```\n[[b]]\n```\n\nreal link: [[c]]",
    )
    _write(tmp_path, "b.md", ".")
    _write(tmp_path, "c.md", ".")

    g = build_link_graph(tmp_path)

    resolved = {t for link in g.outbound["a"] for t in link.resolved_to}
    assert resolved == {"c"}


def test_graph_is_deterministic(tmp_path: Path):
    _write(tmp_path, "a.md", "[[b]] [[c]]")
    _write(tmp_path, "b.md", "[[a]]")
    _write(tmp_path, "c.md", ".")

    g1 = build_link_graph(tmp_path)
    g2 = build_link_graph(tmp_path)

    assert g1 == g2


# --- phase 3.2 detectors --------------------------------------------------


def test_find_broken_links_simple(tmp_path: Path):
    _write(tmp_path, "a.md", "[[b]] and [[ghost]]")
    _write(tmp_path, "b.md", ".")

    g = build_link_graph(tmp_path)
    broken = find_broken_links(g)

    assert len(broken) == 1
    assert broken[0].source == "a"
    assert broken[0].target_raw == "ghost"
    assert broken[0].is_embed is False


def test_find_broken_links_preserves_embed_flag(tmp_path: Path):
    _write(tmp_path, "a.md", "![[missing]]")
    g = build_link_graph(tmp_path)
    broken = find_broken_links(g)
    assert len(broken) == 1
    assert broken[0].is_embed is True


def test_find_one_way_links(tmp_path: Path):
    _write(tmp_path, "a.md", "[[b]]")
    _write(tmp_path, "b.md", "[[c]]")  # no back-link to a
    _write(tmp_path, "c.md", "[[b]]")  # reciprocal with b

    g = build_link_graph(tmp_path)
    one_ways = find_one_way_links(g)

    pairs = {(o.source, o.target) for o in one_ways}
    assert ("a", "b") in pairs  # a→b, no b→a
    assert ("b", "c") not in pairs  # reciprocal
    assert ("c", "b") not in pairs  # reciprocal


def test_find_one_way_skips_broken_links(tmp_path: Path):
    _write(tmp_path, "a.md", "[[ghost]]")  # broken, NOT one-way
    g = build_link_graph(tmp_path)
    assert find_one_way_links(g) == ()


def test_find_orphans_strict_zero_inbound(tmp_path: Path):
    _write(tmp_path, "orphan.md", "[[hub]]")  # outbound ≥ 1, inbound = 0
    _write(tmp_path, "hub.md", "[[leaf]]")
    _write(tmp_path, "leaf.md", ".")  # no outbound → NOT orphan

    g = build_link_graph(tmp_path)
    orphans = find_orphans(g)

    names = {o.node for o in orphans}
    assert names == {"orphan"}


def test_find_orphans_counts_broken_outbound(tmp_path: Path):
    _write(tmp_path, "lonely.md", "[[nowhere]]")  # only outbound is broken

    g = build_link_graph(tmp_path)
    orphans = find_orphans(g)

    assert len(orphans) == 1
    assert orphans[0].node == "lonely"
    assert orphans[0].outbound_count == 1


def test_find_shadowed_links(tmp_path: Path):
    _write(tmp_path, "x/ideas.md", ".")
    _write(tmp_path, "y/ideas.md", ".")
    _write(tmp_path, "a.md", "[[ideas]]")

    g = build_link_graph(tmp_path)
    shadowed = find_shadowed_links(g)

    assert len(shadowed) == 1
    assert shadowed[0].source == "a"
    assert shadowed[0].candidates == ("x/ideas", "y/ideas")


def test_detectors_are_deterministic(tmp_path: Path):
    _write(tmp_path, "a.md", "[[b]] [[ghost]]")
    _write(tmp_path, "b.md", "[[c]]")
    _write(tmp_path, "c.md", ".")

    g = build_link_graph(tmp_path)
    assert find_broken_links(g) == find_broken_links(g)
    assert find_one_way_links(g) == find_one_way_links(g)
    assert find_orphans(g) == find_orphans(g)
    assert find_shadowed_links(g) == find_shadowed_links(g)


def test_audit_vault_composes_everything(tmp_path: Path):
    _write(tmp_path, "a.md", "[[b]] [[ghost]]")
    _write(tmp_path, "b.md", ".")

    report = audit_vault(tmp_path)

    assert report.node_count == 2
    assert len(report.broken) == 1
    assert len(report.one_way) == 1  # a→b with no b→a
    assert len(report.orphans) == 1  # a has outbound, no inbound
    assert len(report.shadowed) == 0
    assert report.total_findings == 3
