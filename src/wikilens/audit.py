"""Link auditing primitives (P3, phase 3.1 — graph model + resolver).

Builds an in-memory wikilink graph over a vault by reusing P2's parsers
(`walk_vault`, `parse_note`, `extract_links`). Detectors (broken / one-way
/ orphan / shadowed) land in phase 3.2 and consume the graph built here.

Design contracts live in the P3 SDD (`docs/p3-decisions.md` when it's
written). Summary of what this module enforces:

- C1 target resolution: basename match (case-insensitive) OR full
  vault-relative path match (case-insensitive). Both are resolved; the
  set of hits is recorded verbatim. Zero hits = broken. Two+ hits =
  shadowed.
- C2 node identity: vault-relative forward-slash path, WITHOUT the
  ``.md`` suffix (so ``foo/bar.md`` is node ``foo/bar``). This matches
  how Obsidian links are written and makes the graph keys line up with
  what users type in ``[[...]]``.
- C6 self-links: dropped at graph-build time. A note linking to itself
  contributes nothing to inbound or outbound edges.
- C7 embeds count: ``![[X]]`` is a graph edge exactly like ``[[X]]``.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from wikilens.ingest import (
    DEFAULT_EXCLUDE,
    DEFAULT_INCLUDE,
    extract_links,
    parse_note,
    walk_vault,
)


@dataclass(frozen=True)
class ResolvedLink:
    """A wikilink from one note to candidate target node(s).

    ``resolved_to`` is a tuple of node keys (C2 form):
      - empty  → broken (no target exists)
      - one    → normal resolution
      - two+   → shadowed (ambiguous basename; graph-level warning)

    ``target_raw`` preserves the exact text the user wrote between
    ``[[`` and ``]]`` (minus heading/alias fragments, which don't affect
    resolution). Useful for reporting output that echoes the user's
    wording back to them.
    """

    source: str
    target_raw: str
    resolved_to: tuple[str, ...]
    is_embed: bool


@dataclass(frozen=True)
class LinkGraph:
    """In-memory wikilink graph for one vault.

    Attributes:
        nodes: every note in the vault, keyed by vault-relative path
            without the ``.md`` suffix (C2).
        outbound: node_key → tuple of outbound ResolvedLinks. Self-links
            are excluded (C6); embeds are included (C7). Duplicate
            links (same source, same resolved target) are deduplicated
            but distinct ``target_raw`` values are preserved as
            separate entries so later detectors can still report the
            specific raw text.
        inbound: node_key → tuple of source node keys that link TO this
            node. Only successfully resolved targets contribute. If a
            link is shadowed across N targets, every one of those N
            targets gets the source in its inbound set.
        by_key: normalized lookup key → tuple of node keys matching
            that key. Keys are lowercase; both basename and full-path
            forms map into this dict, so resolution is a single
            ``dict.get`` per link.
    """

    nodes: frozenset[str]
    outbound: dict[str, tuple[ResolvedLink, ...]]
    inbound: dict[str, tuple[str, ...]]
    by_key: dict[str, tuple[str, ...]]


def _rel_key(path: Path, vault_root: Path) -> str:
    """Vault-relative forward-slash path without the .md suffix (C2)."""
    try:
        rel = path.resolve().relative_to(vault_root.resolve())
    except ValueError:
        rel = Path(path.name)
    rel_posix = rel.as_posix()
    if rel_posix.lower().endswith(".md"):
        rel_posix = rel_posix[:-3]
    return rel_posix


def _normalize_target(target: str) -> str:
    """Normalize a wikilink target string for matching.

    - strip whitespace
    - drop a trailing ``.md`` if the user wrote one
    - collapse backslashes to forward slashes
    - lowercase (case-insensitive match per C1)
    """
    t = target.strip().replace("\\", "/")
    if t.lower().endswith(".md"):
        t = t[:-3]
    return t.lower()


def build_link_graph(
    vault_root: str | Path,
    include: Iterable[str] = DEFAULT_INCLUDE,
    exclude: Iterable[str] = DEFAULT_EXCLUDE,
) -> LinkGraph:
    """Walk the vault, parse every note, resolve every wikilink.

    One pass, no persistence. Returns a fully-populated LinkGraph ready
    for detectors. Notes with frontmatter errors still contribute nodes
    and links — a broken YAML block shouldn't hide the note's graph
    connectivity.
    """
    root = Path(vault_root).resolve()
    paths = walk_vault(root, include=include, exclude=exclude)

    # Pass 1: register every note as a node and build the resolution index.
    node_keys: list[str] = []
    bodies: dict[str, str] = {}
    # Lookup key → list of node keys. Basename and full-path both map in.
    key_index: dict[str, list[str]] = defaultdict(list)

    for p in paths:
        key = _rel_key(p, root)
        node_keys.append(key)
        bodies[key] = parse_note(p).body

        lowered_full = key.lower()
        key_index[lowered_full].append(key)

        basename = key.rsplit("/", 1)[-1].lower()
        if basename != lowered_full:
            key_index[basename].append(key)

    # Dedup within each lookup list while preserving order.
    by_key: dict[str, tuple[str, ...]] = {}
    for k, v in key_index.items():
        seen: set[str] = set()
        uniq: list[str] = []
        for item in v:
            if item in seen:
                continue
            seen.add(item)
            uniq.append(item)
        by_key[k] = tuple(uniq)

    # Pass 2: extract links per note and resolve against by_key.
    outbound: dict[str, list[ResolvedLink]] = {k: [] for k in node_keys}
    inbound_sets: dict[str, set[str]] = {k: set() for k in node_keys}

    for source in node_keys:
        links = extract_links(bodies[source])
        seen_out: set[tuple[str, bool, tuple[str, ...]]] = set()
        for wl in links.wikilinks:
            lookup = _normalize_target(wl.target)
            if not lookup:
                continue
            raw_resolved = by_key.get(lookup, ())
            # C6: drop self from the resolved set. If that empties a set
            # that only ever pointed at self, drop the link entirely
            # (a pure self-link is not a broken link — it's a nothing).
            resolved = tuple(r for r in raw_resolved if r != source)
            if raw_resolved and not resolved:
                continue
            dedup_key = (wl.target, wl.is_embed, resolved)
            if dedup_key in seen_out:
                continue
            seen_out.add(dedup_key)
            outbound[source].append(
                ResolvedLink(
                    source=source,
                    target_raw=wl.target,
                    resolved_to=resolved,
                    is_embed=wl.is_embed,
                )
            )
            for target_node in resolved:
                inbound_sets[target_node].add(source)

    outbound_frozen = {k: tuple(v) for k, v in outbound.items()}
    inbound_frozen = {k: tuple(sorted(v)) for k, v in inbound_sets.items()}

    return LinkGraph(
        nodes=frozenset(node_keys),
        outbound=outbound_frozen,
        inbound=inbound_frozen,
        by_key=by_key,
    )


# ---------------------------------------------------------------------------
# Detectors (phase 3.2): pure functions over LinkGraph.
#
# Each detector returns a deterministically-sorted list of dataclasses. The
# detector functions never mutate the graph and never read the filesystem —
# everything they need is in LinkGraph.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, order=True)
class BrokenLink:
    """A wikilink whose target does not exist in the vault (C3)."""

    source: str
    target_raw: str
    is_embed: bool


@dataclass(frozen=True, order=True)
class OneWayLink:
    """A resolved link A → B with no reciprocal link B → A (C4).

    ``target`` is the resolved node key, not the raw text. ``target_raw``
    is kept for display. If a shadowed link has multiple resolved
    targets, each target is checked for reciprocity independently —
    this can produce up to N OneWayLink entries per raw wikilink.
    """

    source: str
    target: str
    target_raw: str


@dataclass(frozen=True, order=True)
class OrphanNote:
    """A node with ≥1 outbound wikilink and zero inbound links (C5).

    "Outbound wikilink" counts every wikilink in the body, regardless
    of whether it resolves — a note whose only outbound links are
    broken is still an orphan (and arguably more so).
    """

    node: str
    outbound_count: int


@dataclass(frozen=True, order=True)
class ShadowedLink:
    """A wikilink resolving to 2+ notes with the same basename (Q4).

    Not a broken link — the graph resolves the edge to every candidate
    — but flagged so the author can disambiguate before a future
    refactor silently changes which target wins.
    """

    source: str
    target_raw: str
    candidates: tuple[str, ...]


@dataclass(frozen=True)
class AuditReport:
    """Container for all detector outputs from one audit run."""

    vault_root: Path
    node_count: int
    broken: tuple[BrokenLink, ...]
    one_way: tuple[OneWayLink, ...]
    orphans: tuple[OrphanNote, ...]
    shadowed: tuple[ShadowedLink, ...]

    @property
    def total_findings(self) -> int:
        return len(self.broken) + len(self.one_way) + len(self.orphans) + len(self.shadowed)


def find_broken_links(graph: LinkGraph) -> tuple[BrokenLink, ...]:
    """Every wikilink whose ``resolved_to`` is empty."""
    out: list[BrokenLink] = []
    for source in sorted(graph.outbound):
        for link in graph.outbound[source]:
            if not link.resolved_to:
                out.append(
                    BrokenLink(
                        source=source,
                        target_raw=link.target_raw,
                        is_embed=link.is_embed,
                    )
                )
    return tuple(sorted(out))


def find_one_way_links(graph: LinkGraph) -> tuple[OneWayLink, ...]:
    """A → B resolved but B has no wikilink resolving back to A (C4).

    Uses ``graph.inbound`` for O(1) reciprocity checks. Shadowed links
    are checked per-resolved-target.
    """
    out: list[OneWayLink] = []
    for source in sorted(graph.outbound):
        for link in graph.outbound[source]:
            for target in link.resolved_to:
                # Reciprocal iff the target also links back to the source,
                # i.e. the target appears in the source's inbound set.
                if target not in graph.inbound.get(source, ()):
                    out.append(
                        OneWayLink(
                            source=source,
                            target=target,
                            target_raw=link.target_raw,
                        )
                    )
    return tuple(sorted(out))


def find_orphans(graph: LinkGraph) -> tuple[OrphanNote, ...]:
    """Strict zero-inbound with ≥1 outbound wikilink (C5)."""
    out: list[OrphanNote] = []
    for node in sorted(graph.nodes):
        outbound_count = len(graph.outbound.get(node, ()))
        inbound_count = len(graph.inbound.get(node, ()))
        if outbound_count >= 1 and inbound_count == 0:
            out.append(OrphanNote(node=node, outbound_count=outbound_count))
    return tuple(sorted(out))


def find_shadowed_links(graph: LinkGraph) -> tuple[ShadowedLink, ...]:
    """Wikilinks resolved to 2+ candidates (Q4 warning class)."""
    out: list[ShadowedLink] = []
    for source in sorted(graph.outbound):
        for link in graph.outbound[source]:
            if len(link.resolved_to) >= 2:
                out.append(
                    ShadowedLink(
                        source=source,
                        target_raw=link.target_raw,
                        candidates=tuple(sorted(link.resolved_to)),
                    )
                )
    return tuple(sorted(out))


def audit_vault(
    vault_root: str | Path,
    include: Iterable[str] = DEFAULT_INCLUDE,
    exclude: Iterable[str] = DEFAULT_EXCLUDE,
) -> AuditReport:
    """Build the graph and run every detector. Convenience entry point."""
    graph = build_link_graph(vault_root, include=include, exclude=exclude)
    return AuditReport(
        vault_root=Path(vault_root).resolve(),
        node_count=len(graph.nodes),
        broken=find_broken_links(graph),
        one_way=find_one_way_links(graph),
        orphans=find_orphans(graph),
        shadowed=find_shadowed_links(graph),
    )
