"""Tests for the ingest manifest (M4.1) and incremental ingest behavior (M4.11)."""

from __future__ import annotations

import json
from pathlib import Path

from wikilens.manifest import (
    FileEntry,
    IngestManifest,
    hash_file,
    load_manifest,
    save_manifest,
    scan_vault_state,
)


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


class TestHashFile:
    def test_deterministic(self, tmp_path: Path):
        f = _write(tmp_path / "a.md", "hello world")
        assert hash_file(f) == hash_file(f)

    def test_different_content_different_hash(self, tmp_path: Path):
        a = _write(tmp_path / "a.md", "hello")
        b = _write(tmp_path / "b.md", "world")
        assert hash_file(a) != hash_file(b)

    def test_returns_32_hex_chars(self, tmp_path: Path):
        f = _write(tmp_path / "x.md", "test")
        h = hash_file(f)
        assert len(h) == 32
        assert all(c in "0123456789abcdef" for c in h)


class TestManifestDiff:
    def test_empty_to_files_all_added(self):
        m = IngestManifest()
        current = {"a.md": FileEntry("aaa", 1), "b.md": FileEntry("bbb", 2)}
        added, changed, removed = m.diff(current)
        assert added == ["a.md", "b.md"]
        assert changed == []
        assert removed == []

    def test_unchanged_files_not_in_diff(self):
        m = IngestManifest(entries={"a.md": FileEntry("aaa", 1)})
        current = {"a.md": FileEntry("aaa", 1)}
        added, changed, removed = m.diff(current)
        assert added == []
        assert changed == []
        assert removed == []

    def test_changed_file_detected(self):
        m = IngestManifest(entries={"a.md": FileEntry("aaa", 1)})
        current = {"a.md": FileEntry("bbb", 2)}
        added, changed, removed = m.diff(current)
        assert changed == ["a.md"]

    def test_removed_file_detected(self):
        m = IngestManifest(entries={"a.md": FileEntry("aaa", 1), "b.md": FileEntry("bbb", 2)})
        current = {"a.md": FileEntry("aaa", 1)}
        added, changed, removed = m.diff(current)
        assert removed == ["b.md"]

    def test_mixed_operations(self):
        m = IngestManifest(
            entries={
                "keep.md": FileEntry("k", 1),
                "edit.md": FileEntry("old", 2),
                "gone.md": FileEntry("g", 3),
            }
        )
        current = {
            "keep.md": FileEntry("k", 1),
            "edit.md": FileEntry("new", 4),
            "fresh.md": FileEntry("f", 5),
        }
        added, changed, removed = m.diff(current)
        assert added == ["fresh.md"]
        assert changed == ["edit.md"]
        assert removed == ["gone.md"]


class TestManifestPersistence:
    def test_save_and_load_roundtrip(self, tmp_path: Path):
        db = tmp_path / "db"
        db.mkdir()
        m = IngestManifest(
            entries={"x.md": FileEntry("abc123", 999)}
        )
        save_manifest(db, m)
        loaded = load_manifest(db)
        assert loaded.version == 1
        assert "x.md" in loaded.entries
        assert loaded.entries["x.md"].content_hash == "abc123"
        assert loaded.entries["x.md"].mtime_ns == 999

    def test_load_missing_returns_empty(self, tmp_path: Path):
        m = load_manifest(tmp_path / "nonexistent")
        assert m.entries == {}

    def test_load_corrupt_json_returns_empty(self, tmp_path: Path):
        db = tmp_path / "db"
        db.mkdir()
        (db / ".wikilens_manifest.json").write_text("not json", encoding="utf-8")
        m = load_manifest(db)
        assert m.entries == {}

    def test_load_wrong_version_returns_empty(self, tmp_path: Path):
        db = tmp_path / "db"
        db.mkdir()
        (db / ".wikilens_manifest.json").write_text(
            json.dumps({"version": 99, "entries": {}}), encoding="utf-8"
        )
        m = load_manifest(db)
        assert m.entries == {}


class TestScanVaultState:
    def test_scans_files(self, tmp_path: Path):
        vault = tmp_path / "vault"
        vault.mkdir()
        _write(vault / "a.md", "hello")
        _write(vault / "sub" / "b.md", "world")
        paths = [vault / "a.md", vault / "sub" / "b.md"]
        state = scan_vault_state(paths, vault)
        assert "a.md" in state
        assert "sub/b.md" in state
        assert state["a.md"].content_hash == hash_file(vault / "a.md")
