from __future__ import annotations

import io

import pytest
from ebooklib import epub
from starlette.testclient import TestClient

from app.ingest import docs_to_chunks, extract_epub
from app.rag import LibraryRAGIndex


def minimal_epub_bytes() -> bytes:
    book = epub.EpubBook()
    book.set_identifier("test-epub-ingest")
    book.set_title("Carte test")
    book.set_language("ro")
    book.add_author("Autor Test")
    c1 = epub.EpubHtml(title="Capitol 1", file_name="ch1.xhtml", lang="ro")
    c1.content = b"<html><body><h1>Unu</h1><p>EPUB_UNIQUE_MARKER_ALPHA pentru RAG.</p></body></html>"
    book.add_item(c1)
    c2 = epub.EpubHtml(title="Capitol 2", file_name="ch2.xhtml", lang="ro")
    c2.content = b"<html><body><p>Al doilea fragment.</p></body></html>"
    book.add_item(c2)
    book.toc = (c1, c2)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", c1, c2]
    buf = io.BytesIO()
    epub.write_epub(buf, book, {})
    return buf.getvalue()


def test_extract_epub_two_chapters() -> None:
    doc = extract_epub(filename="x.epub", content=minimal_epub_bytes())
    assert doc.source_type == "epub"
    assert len(doc.pages) >= 2
    joined = "\n".join(doc.pages)
    assert "EPUB_UNIQUE_MARKER_ALPHA" in joined
    assert doc.meta.get("title") == "Carte test"
    assert doc.meta.get("chapter_count") == len(doc.pages)


def test_docs_to_chunks_epub_has_chapter_metadata() -> None:
    doc = extract_epub(filename="x.epub", content=minimal_epub_bytes())
    texts, metas, _ids = docs_to_chunks(doc=doc)
    assert texts
    chapters = {m.get("chapter") for m in metas if m.get("source_type") == "epub"}
    assert 1 in chapters
    assert 2 in chapters


@pytest.fixture
def client() -> TestClient:
    from app.main import app

    return TestClient(app)


def test_ingest_epub_via_api(client: TestClient, tmp_path_factory: pytest.TempPathFactory) -> None:
    """Folosește vectorstore temporar prin monkeypatch pe app — TestClient folosește același rag importat."""
    import app.main as main_mod

    old_dir = main_mod.VECTORSTORE_DIR
    old_rag = main_mod.rag
    vs = tmp_path_factory.mktemp("vs")
    try:
        main_mod.VECTORSTORE_DIR = vs
        main_mod.rag = LibraryRAGIndex(persist_dir=vs)
        files = {
            "files": ("test.epub", minimal_epub_bytes(), "application/epub+zip"),
        }
        r = client.post("/ingest/files", files=files)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("status") == "ok"
        summaries = data.get("files") or []
        assert summaries and summaries[0].get("status") == "ok"
        assert summaries[0].get("source_type") == "epub"
        assert summaries[0].get("chunks_added", 0) > 0
        hits = main_mod.rag.query("EPUB_UNIQUE_MARKER_ALPHA", k=5)
        assert any("EPUB_UNIQUE_MARKER_ALPHA" in (h.get("text") or "") for h in hits)
    finally:
        main_mod.VECTORSTORE_DIR = old_dir
        main_mod.rag = old_rag
