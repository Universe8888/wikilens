"""End-to-end ingestion pipeline: vault → chunks → embeddings → store.

Composes the step-2 walker, step-3 parser, step-5 chunker, step-6 embedder,
and step-7 store. Idempotent: re-running on the same vault replaces rows
in place via deterministic chunk_ids (step 5 design).
"""

from __future__ import annotations

from collections.abc import Iterable
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
from wikilens.store import LanceDBStore, VectorStore


@dataclass(frozen=True)
class IngestReport:
    """Counts + flagged issues from a single ingest run."""

    vault_root: Path
    files_scanned: int
    files_parsed: int
    files_with_frontmatter_errors: int
    chunks_emitted: int
    chunks_indexed: int

    def summary(self) -> str:
        lines = [
            f"vault: {self.vault_root}",
            f"  files scanned: {self.files_scanned}",
            f"  files parsed:  {self.files_parsed}",
            f"  chunks:        {self.chunks_emitted} emitted, {self.chunks_indexed} indexed",
        ]
        if self.files_with_frontmatter_errors:
            lines.append(
                f"  ⚠ frontmatter errors in {self.files_with_frontmatter_errors} files"
            )
        return "\n".join(lines)


def _iter_notes_and_chunks(
    paths: Iterable[Path],
    vault_root: Path,
) -> tuple[list[Note], list[Chunk]]:
    notes: list[Note] = []
    chunks: list[Chunk] = []
    for p in paths:
        note = parse_note(p)
        notes.append(note)
        chunks.extend(chunk_note(note, vault_root=vault_root))
    return notes, chunks


def ingest_vault(
    vault_root: str | Path,
    db_path: str | Path,
    embedder: Embedder | None = None,
    store: VectorStore | None = None,
    include: Iterable[str] = DEFAULT_INCLUDE,
    exclude: Iterable[str] = DEFAULT_EXCLUDE,
    batch_size: int = 64,
) -> IngestReport:
    """Ingest every markdown file in `vault_root` into the store at `db_path`.

    Returns an IngestReport. Re-running on the same vault is safe: chunks
    with identical chunk_ids replace prior rows in place.
    """
    vault = Path(vault_root).resolve()

    paths = walk_vault(vault, include=include, exclude=exclude)
    files_scanned = len(paths)

    notes, chunks = _iter_notes_and_chunks(paths, vault)
    files_parsed = len(notes)
    files_with_fm_errors = sum(1 for n in notes if n.frontmatter_error)

    if embedder is None:
        embedder = BGEEmbedder()
    if store is None:
        store = LanceDBStore(db_path=db_path, dim=embedder.dim)

    indexed = 0
    if chunks:
        # Batched embedding so we don't blow memory on large vaults.
        for start in range(0, len(chunks), batch_size):
            batch = chunks[start : start + batch_size]
            vecs = embedder.encode_passages([c.text for c in batch])
            indexed += store.upsert(batch, vecs)

        # Ensure FTS index is (re)built now, not lazily on first query.
        if isinstance(store, LanceDBStore):
            store.ensure_fts_index()

    return IngestReport(
        vault_root=vault,
        files_scanned=files_scanned,
        files_parsed=files_parsed,
        files_with_frontmatter_errors=files_with_fm_errors,
        chunks_emitted=len(chunks),
        chunks_indexed=indexed,
    )
