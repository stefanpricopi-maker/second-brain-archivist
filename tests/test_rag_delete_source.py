from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from app.rag import LibraryRAGIndex


def test_delete_by_source_batches(tmp_path: Path) -> None:
    rag = LibraryRAGIndex(persist_dir=tmp_path / "vs")
    for i in range(5):
        rag.add_texts(
            ids=[f"id-{i}"],
            texts=[f"t{i}"],
            metadatas=[{"source": "keep.pdf", "chunk": i}],
        )
    for i in range(5):
        rag.add_texts(
            ids=[f"drop-{i}"],
            texts=[f"d{i}"],
            metadatas=[{"source": "drop.pdf", "chunk": i}],
        )
    n = rag.delete_by_source(source="drop.pdf")
    assert n == 5
    assert rag.count() == 5


@pytest.fixture
def client() -> TestClient:
    from app.main import app

    return TestClient(app)


def test_voice_library_delete_index(client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.main as main_mod

    r = LibraryRAGIndex(persist_dir=tmp_path / "vs_del")
    r.add_texts(
        ids=["a", "b"],
        texts=["x", "y"],
        metadatas=[{"source": "book.pdf", "chunk": 1}, {"source": "other.pdf", "chunk": 1}],
    )
    monkeypatch.setattr(main_mod, "rag", r)

    resp = client.delete("/voice-library/index", params={"source": "book.pdf"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["deleted_chunks"] == 1
    assert body["rag_chunks"] == 1
    assert body["source"] == "book.pdf"


def test_voice_library_delete_index_requires_source(client: TestClient) -> None:
    r = client.delete("/voice-library/index")
    assert r.status_code == 422


def test_voice_library_delete_index_source_too_long(client: TestClient) -> None:
    r = client.delete("/voice-library/index", params={"source": "x" * 600})
    assert r.status_code == 422
