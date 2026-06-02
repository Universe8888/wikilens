"""M4.11 integration tests — prove incremental ingest is correct.

Tests verify:
- Edit one note → only that note re-embeds
- Delete a note → exactly its rows gone
- --rebuild reproduces from scratch
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from wikilens.embed import BGEEmbedder
from wikilens.pipeline import ingest_vault
from wikilens.store import LanceDBStore


@pytest.fixture(scope="module")
def embedder() -> BGEEmbedder:
    e = BGEEmbedder()
    e._ensure_model()
    return e


def _write(root: Path, rel: str, body: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


class TestEditOneNote:
    def test_only_edited_note_re_embeds(self, tmp_path: Path, embedder: BGEEmbedder):
        vault = tmp_path / "vault"
        vault.mkdir()
        _write(vault, "stable.md", "# Stable\n\nThis note never changes.\n")
        _write(vault, "editable.md", "# Edit\n\nOriginal content here.\n")

        db = tmp_path / "db"
        r1 = ingest_vault(vault, db_path=db, embedder=embedder)
        assert r1.files_parsed == 2

        # Edit one file
        _write(vault, "editable.md", "# Edit\n\nUpdated content with new info.\n")

        # Track embedder calls
        call_count = [0]
        original_encode = embedder.encode_passages

        def counting_encode(texts):
            call_count[0] += len(texts)
            return original_encode(texts)

        with patch.object(embedder, "encode_passages", side_effect=counting_encode):
            r2 = ingest_vault(vault, db_path=db, embedder=embedder)

        # Only the edited file's chunks should be re-embedded
        assert r2.files_parsed == 1
        assert r2.files_unchanged == 1
        assert r2.chunks_emitted >= 1
        assert call_count[0] == r2.chunks_emitted

        # Store should have the right total
        store = LanceDBStore(db_path=db, dim=embedder.dim)
        assert store.count() == r1.chunks_indexed  # same total (1 file + 1 file)


class TestDeleteNote:
    def test_deleted_note_rows_removed(self, tmp_path: Path, embedder: BGEEmbedder):
        vault = tmp_path / "vault"
        vault.mkdir()
        doomed = _write(vault, "doomed.md", "# Doomed\n\nThis will be deleted.\n")
        _write(vault, "survivor.md", "# Survivor\n\nThis stays.\n")

        db = tmp_path / "db"
        r1 = ingest_vault(vault, db_path=db, embedder=embedder)
        initial_count = r1.chunks_indexed
        assert initial_count >= 2

        # Delete the file
        doomed.unlink()
        r2 = ingest_vault(vault, db_path=db, embedder=embedder)

        assert r2.files_removed == 1
        assert r2.chunks_removed >= 1
        assert r2.chunks_emitted == 0  # survivor unchanged

        # Fresh store connection to verify state after delete
        store = LanceDBStore(db_path=db, dim=embedder.dim)
        rows = store.iter_rows(["source_rel"])
        source_rels = {row["source_rel"] for row in rows}
        assert "doomed.md" not in source_rels
        assert "survivor.md" in source_rels
        assert store.count() == initial_count - r2.chunks_removed


class TestRebuildFlag:
    def test_rebuild_reproduces_from_scratch(self, tmp_path: Path, embedder: BGEEmbedder):
        vault = tmp_path / "vault"
        vault.mkdir()
        _write(vault, "a.md", "# A\n\nalpha.\n")
        _write(vault, "b.md", "# B\n\nbeta.\n")

        db = tmp_path / "db"
        r1 = ingest_vault(vault, db_path=db, embedder=embedder)

        # Rebuild should process all files regardless of manifest
        r2 = ingest_vault(vault, db_path=db, embedder=embedder, rebuild=True)

        assert r2.files_parsed == 2
        assert r2.chunks_emitted == r1.chunks_emitted
        store = LanceDBStore(db_path=db, dim=embedder.dim)
        assert store.count() == r1.chunks_indexed

    def test_rebuild_cleans_stale_rows(self, tmp_path: Path, embedder: BGEEmbedder):
        vault = tmp_path / "vault"
        vault.mkdir()
        _write(vault, "a.md", "# A\n\nalpha.\n")
        doomed = _write(vault, "b.md", "# B\n\nbeta.\n")

        db = tmp_path / "db"
        ingest_vault(vault, db_path=db, embedder=embedder)

        # Delete a file but DON'T do incremental — jump to rebuild
        doomed.unlink()
        r = ingest_vault(vault, db_path=db, embedder=embedder, rebuild=True)

        store = LanceDBStore(db_path=db, dim=embedder.dim)
        rows = store.iter_rows(["source_rel"])
        source_rels = {row["source_rel"] for row in rows}
        assert "b.md" not in source_rels
        assert store.count() == r.chunks_indexed
