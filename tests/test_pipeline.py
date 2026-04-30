"""End-to-end ingest pipeline tests.

Uses the real BGE model and a real LanceDB store on tmp_path — these are
integration tests, not unit tests. Slower (~2-3s once model cached) but
they validate the wiring actually works.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from wikilens.embed import BGEEmbedder
from wikilens.pipeline import IngestReport, ingest_vault
from wikilens.store import LanceDBStore


@pytest.fixture(scope="module")
def embedder() -> BGEEmbedder:
    e = BGEEmbedder()
    e._ensure_model()
    return e


def _make_note(root: Path, rel: str, body: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


def test_ingest_empty_vault(tmp_path: Path, embedder: BGEEmbedder):
    vault = tmp_path / "vault"
    vault.mkdir()
    report = ingest_vault(
        vault,
        db_path=tmp_path / "db",
        embedder=embedder,
    )
    assert isinstance(report, IngestReport)
    assert report.files_scanned == 0
    assert report.chunks_emitted == 0
    assert report.chunks_indexed == 0


def test_ingest_small_vault_roundtrip(tmp_path: Path, embedder: BGEEmbedder):
    vault = tmp_path / "vault"
    vault.mkdir()
    _make_note(
        vault,
        "bio.md",
        "# Biology\n\n## Photosynthesis\n\n"
        "Plants convert sunlight, water, and CO2 into glucose and oxygen.\n",
    )
    _make_note(
        vault,
        "physics.md",
        "# Physics\n\n## Gravity\n\nMass attracts mass. Newton figured this out.\n",
    )

    report = ingest_vault(
        vault,
        db_path=tmp_path / "db",
        embedder=embedder,
    )

    assert report.files_scanned == 2
    assert report.files_parsed == 2
    assert report.chunks_emitted >= 2  # at least one per file
    assert report.chunks_indexed == report.chunks_emitted
    assert report.files_with_frontmatter_errors == 0

    # Verify retrievability end-to-end
    store = LanceDBStore(db_path=tmp_path / "db", dim=embedder.dim)
    assert store.count() == report.chunks_indexed

    q = embedder.encode_query("how plants make food")
    hits = store.search_dense(q, k=3)
    assert len(hits) >= 1
    assert "bio.md" in hits[0].source_rel


def test_ingest_is_idempotent(tmp_path: Path, embedder: BGEEmbedder):
    vault = tmp_path / "vault"
    vault.mkdir()
    _make_note(vault, "a.md", "# A\n\nalpha content here.\n")
    _make_note(vault, "b.md", "# B\n\nbeta content here.\n")

    db = tmp_path / "db"
    first = ingest_vault(vault, db_path=db, embedder=embedder)
    second = ingest_vault(vault, db_path=db, embedder=embedder)

    # Same chunks emitted + same count indexed; store total should not double
    assert second.chunks_emitted == first.chunks_emitted
    store = LanceDBStore(db_path=db, dim=embedder.dim)
    assert store.count() == first.chunks_indexed


def test_ingest_picks_up_new_file_on_rerun(tmp_path: Path, embedder: BGEEmbedder):
    vault = tmp_path / "vault"
    vault.mkdir()
    _make_note(vault, "a.md", "alpha")
    db = tmp_path / "db"
    r1 = ingest_vault(vault, db_path=db, embedder=embedder)

    _make_note(vault, "b.md", "beta")
    r2 = ingest_vault(vault, db_path=db, embedder=embedder)

    assert r2.chunks_emitted > r1.chunks_emitted
    store = LanceDBStore(db_path=db, dim=embedder.dim)
    assert store.count() == r2.chunks_emitted


def test_ingest_flags_frontmatter_errors(tmp_path: Path, embedder: BGEEmbedder):
    vault = tmp_path / "vault"
    vault.mkdir()
    _make_note(vault, "good.md", "# Good\n\ncontent\n")
    _make_note(vault, "bad.md", "---\ntitle: [unclosed\n---\nbody\n")
    report = ingest_vault(vault, db_path=tmp_path / "db", embedder=embedder)
    assert report.files_with_frontmatter_errors == 1
    # Still gets ingested — the body after the fence is usable
    assert report.chunks_emitted >= 2
