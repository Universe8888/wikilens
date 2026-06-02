"""End-to-end ingestion pipeline: vault → chunks → embeddings → store.

Supports incremental ingest (O(delta)) via a manifest that tracks file content
hashes. Only new/changed files are re-chunked and re-embedded. Deleted files
have their chunks removed from the store.
"""

from __future__ import annotations

import logging
from collections.abc import Generator, Iterable
from dataclasses import dataclass
from pathlib import Path

from wikilens.embed import BGEEmbedder, Embedder
from wikilens.ingest import (
    DEFAULT_EXCLUDE,
    DEFAULT_INCLUDE,
    Chunk,
    Note,
    chunk_note,
    parse_note,
    walk_vault,
)
from wikilens.manifest import (
    IngestManifest,
    load_manifest,
    save_manifest,
    scan_vault_state,
)
from wikilens.store import LanceDBStore, VectorStore

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class IngestReport:
    """Counts + flagged issues from a single ingest run."""

    vault_root: Path
    files_scanned: int
    files_parsed: int
    files_with_frontmatter_errors: int
    chunks_emitted: int
    chunks_indexed: int
    files_unchanged: int = 0
    files_removed: int = 0
    chunks_removed: int = 0

    def summary(self) -> str:
        lines = [
            f"vault: {self.vault_root}",
            f"  files scanned: {self.files_scanned}",
            f"  files parsed:  {self.files_parsed}",
            f"  chunks:        {self.chunks_emitted} emitted, {self.chunks_indexed} indexed",
        ]
        if self.files_unchanged:
            lines.append(f"  unchanged:     {self.files_unchanged} files skipped")
        if self.files_removed:
            lines.append(
                f"  removed:       {self.files_removed} files ({self.chunks_removed} chunks)"
            )
        if self.files_with_frontmatter_errors:
            lines.append(
                f"  ⚠ frontmatter errors in {self.files_with_frontmatter_errors} files"
            )
        return "\n".join(lines)


def _iter_chunks_streaming(
    paths: Iterable[Path],
    vault_root: Path,
) -> Generator[tuple[Note, list[Chunk]], None, None]:
    """Yield (note, chunks) per file — never holds entire vault in memory."""
    for p in paths:
        note = parse_note(p)
        chunks = chunk_note(note, vault_root=vault_root)
        yield note, chunks


def ingest_vault(
    vault_root: str | Path,
    db_path: str | Path,
    embedder: Embedder | None = None,
    store: VectorStore | None = None,
    include: Iterable[str] = DEFAULT_INCLUDE,
    exclude: Iterable[str] = DEFAULT_EXCLUDE,
    batch_size: int = 64,
    rebuild: bool = False,
) -> IngestReport:
    """Ingest markdown files into the store, incrementally by default.

    Only files whose content changed since the last ingest are re-processed.
    Pass rebuild=True for a full rebuild (drops all existing data).
    """
    vault = Path(vault_root).resolve()

    if embedder is None:
        embedder = BGEEmbedder()
    if store is None:
        store = LanceDBStore(db_path=db_path, dim=embedder.dim)

    paths = walk_vault(vault, include=include, exclude=exclude)
    files_scanned = len(paths)

    # Full rebuild: drop everything and re-ingest
    if rebuild:
        if isinstance(store, LanceDBStore):
            store.reset()
        return _ingest_all(
            vault, paths, embedder, store, db_path, files_scanned, batch_size
        )

    # Incremental: diff manifest against current vault state
    manifest = load_manifest(db_path)
    current_state = scan_vault_state(paths, vault)
    added, changed, removed = manifest.diff(current_state)

    # Delete chunks for removed and changed files (changed files get new chunk_ids)
    chunks_removed = 0
    for rel in removed + changed:
        if isinstance(store, LanceDBStore):
            chunks_removed += store.delete_by_source_rel(rel)

    # Determine which files to process
    to_process_rels = set(added) | set(changed)
    files_unchanged = files_scanned - len(to_process_rels) - len(removed)

    # Map rel → path for files we need to process
    rel_to_path = {
        p.relative_to(vault).as_posix().replace("\\", "/"): p for p in paths
    }
    paths_to_process = [rel_to_path[rel] for rel in sorted(to_process_rels)]

    # Stream chunks from changed/added files only
    files_parsed = 0
    files_with_fm_errors = 0
    chunks_emitted = 0
    indexed = 0
    pending_chunks: list[Chunk] = []

    for note, chunks in _iter_chunks_streaming(paths_to_process, vault):
        files_parsed += 1
        if note.frontmatter_error:
            files_with_fm_errors += 1
        chunks_emitted += len(chunks)
        pending_chunks.extend(chunks)

        # Flush when batch is full
        while len(pending_chunks) >= batch_size:
            batch = pending_chunks[:batch_size]
            pending_chunks = pending_chunks[batch_size:]
            vecs = embedder.encode_passages([c.text for c in batch])
            indexed += store.upsert(batch, vecs)

    # Flush remainder
    if pending_chunks:
        vecs = embedder.encode_passages([c.text for c in pending_chunks])
        indexed += store.upsert(pending_chunks, vecs)

    # Rebuild FTS only if rows actually changed
    if (indexed > 0 or chunks_removed > 0) and isinstance(store, LanceDBStore):
        store.ensure_fts_index()

    # Update manifest with full current state
    manifest.entries = {
        rel: current_state[rel] for rel in current_state
    }
    save_manifest(db_path, manifest)

    return IngestReport(
        vault_root=vault,
        files_scanned=files_scanned,
        files_parsed=files_parsed,
        files_with_frontmatter_errors=files_with_fm_errors,
        chunks_emitted=chunks_emitted,
        chunks_indexed=indexed,
        files_unchanged=files_unchanged,
        files_removed=len(removed),
        chunks_removed=chunks_removed,
    )


def _ingest_all(
    vault: Path,
    paths: list[Path],
    embedder: Embedder,
    store: VectorStore,
    db_path: str | Path,
    files_scanned: int,
    batch_size: int,
) -> IngestReport:
    """Full ingest — process all files, no manifest check."""
    files_parsed = 0
    files_with_fm_errors = 0
    chunks_emitted = 0
    indexed = 0
    pending_chunks: list[Chunk] = []

    for note, chunks in _iter_chunks_streaming(paths, vault):
        files_parsed += 1
        if note.frontmatter_error:
            files_with_fm_errors += 1
        chunks_emitted += len(chunks)
        pending_chunks.extend(chunks)

        while len(pending_chunks) >= batch_size:
            batch = pending_chunks[:batch_size]
            pending_chunks = pending_chunks[batch_size:]
            vecs = embedder.encode_passages([c.text for c in batch])
            indexed += store.upsert(batch, vecs)

    if pending_chunks:
        vecs = embedder.encode_passages([c.text for c in pending_chunks])
        indexed += store.upsert(pending_chunks, vecs)

    if indexed > 0 and isinstance(store, LanceDBStore):
        store.ensure_fts_index()

    # Save manifest for future incremental runs
    current_state = scan_vault_state(paths, vault)
    manifest = IngestManifest(entries=current_state)
    save_manifest(db_path, manifest)

    return IngestReport(
        vault_root=vault,
        files_scanned=files_scanned,
        files_parsed=files_parsed,
        files_with_frontmatter_errors=files_with_fm_errors,
        chunks_emitted=chunks_emitted,
        chunks_indexed=indexed,
    )
