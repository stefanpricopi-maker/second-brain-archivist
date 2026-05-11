from __future__ import annotations

from pathlib import Path

import pytest

from app.ingest import ingest_bytes_into_rag
from app.rag import LibraryRAGIndex


@pytest.fixture
def rag(tmp_path: Path) -> LibraryRAGIndex:
    return LibraryRAGIndex(persist_dir=tmp_path / "vs")


def test_ingest_markdown_into_rag(rag: LibraryRAGIndex) -> None:
    r = ingest_bytes_into_rag(
        rag,
        filename="note.md",
        content=b"# Titlu\n\nText unic pentru test ingest drive.",
        mime_type="text/markdown",
        extra_meta={"origin": "google_drive", "drive_file_id": "fake123"},
    )
    assert r["status"] == "ok"
    assert r["chunks_added"] >= 1
    hits = rag.query("unic pentru test", k=4)
    assert hits
    assert any("unic" in (h.get("text") or "").lower() for h in hits)


def test_ingest_unsupported_mime(rag: LibraryRAGIndex) -> None:
    r = ingest_bytes_into_rag(
        rag,
        filename="f.xyz",
        content=b"\x00\x01binary",
        mime_type="application/octet-stream",
    )
    assert r["status"] == "error"
    assert r["chunks_added"] == 0
