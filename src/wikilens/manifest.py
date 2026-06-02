"""Ingest manifest — tracks which files have been indexed and their content hashes.

The manifest is a JSON sidecar stored alongside the vector DB. It maps each
ingested file's relative path to its mtime_ns and content hash, enabling O(delta)
incremental ingest: only files whose content changed get re-chunked and re-embedded.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

MANIFEST_FILENAME = ".wikilens_manifest.json"
MANIFEST_VERSION = 1


@dataclass
class FileEntry:
    """State of a single ingested file."""

    content_hash: str  # sha256 of file bytes, hex[:32]
    mtime_ns: int  # os.stat st_mtime_ns


@dataclass
class IngestManifest:
    """Tracks ingested file state for incremental diffing."""

    version: int = MANIFEST_VERSION
    entries: dict[str, FileEntry] = field(default_factory=dict)

    def diff(
        self, current_files: dict[str, FileEntry]
    ) -> tuple[list[str], list[str], list[str]]:
        """Compare manifest against current vault state.

        Returns (added, changed, removed) lists of relative paths.
        """
        old_keys = set(self.entries.keys())
        new_keys = set(current_files.keys())

        added = sorted(new_keys - old_keys)
        removed = sorted(old_keys - new_keys)

        changed = []
        for rel in sorted(old_keys & new_keys):
            if self.entries[rel].content_hash != current_files[rel].content_hash:
                changed.append(rel)

        return added, changed, removed


def hash_file(path: Path) -> str:
    """SHA-256 of file content, truncated to 32 hex chars."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()[:32]


def scan_vault_state(
    paths: list[Path], vault_root: Path
) -> dict[str, FileEntry]:
    """Build current file state from a list of vault paths."""
    state: dict[str, FileEntry] = {}
    for p in paths:
        try:
            rel = p.relative_to(vault_root).as_posix().replace("\\", "/")
        except ValueError:
            rel = p.name
        mtime_ns = p.stat().st_mtime_ns
        state[rel] = FileEntry(content_hash=hash_file(p), mtime_ns=mtime_ns)
    return state


def load_manifest(db_path: str | Path) -> IngestManifest:
    """Load manifest from disk. Returns empty manifest if not found."""
    manifest_path = Path(db_path) / MANIFEST_FILENAME
    if not manifest_path.exists():
        return IngestManifest()
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        if data.get("version", 0) != MANIFEST_VERSION:
            _log.warning("Manifest version mismatch; treating as empty")
            return IngestManifest()
        entries = {
            rel: FileEntry(
                content_hash=e["content_hash"], mtime_ns=e["mtime_ns"]
            )
            for rel, e in data.get("entries", {}).items()
        }
        return IngestManifest(version=data["version"], entries=entries)
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        _log.warning("Corrupt manifest, treating as empty: %s", exc)
        return IngestManifest()


def save_manifest(db_path: str | Path, manifest: IngestManifest) -> None:
    """Persist manifest to disk alongside the vector store."""
    manifest_path = Path(db_path) / MANIFEST_FILENAME
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {
        "version": manifest.version,
        "entries": {
            rel: {"content_hash": e.content_hash, "mtime_ns": e.mtime_ns}
            for rel, e in manifest.entries.items()
        },
    }
    manifest_path.write_text(
        json.dumps(data, indent=2, sort_keys=True), encoding="utf-8"
    )
