from __future__ import annotations

from pathlib import Path

from app.rag import LibraryRAGIndex


def test_list_sources_marks_scan_derived(tmp_path: Path) -> None:
    rag = LibraryRAGIndex(persist_dir=tmp_path / "vs")
    rag.add_texts(
        ids=["a1"],
        texts=["fragment"],
        metadatas=[
            {
                "source": "book.pdf",
                "chunk": 1,
                "source_type": "pdf",
                "voice_shelf": True,
                "scan_derived": True,
            }
        ],
    )
    rows = rag.list_sources()
    assert rows and rows[0].get("scanned_pdf") is True
