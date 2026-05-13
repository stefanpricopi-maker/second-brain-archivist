from __future__ import annotations

from app.ingest import (
    ExtractedDoc,
    _chunk_params_for_doc,
    _dedupe_consecutive_lines,
    _split_sentences_ro,
    docs_to_chunks,
)


def test_dedupe_consecutive_lines() -> None:
    assert _dedupe_consecutive_lines("a\na\nb\na\n") == "a\nb\na"


def test_chunk_params_smaller_for_scanned() -> None:
    d = ExtractedDoc("x.pdf", "scanned_pdf", ["p"], {"ocr": True})
    size, overlap = _chunk_params_for_doc(d)
    assert size <= 1200
    assert overlap <= 200
    assert overlap < size


def test_chunk_params_default_for_text_pdf() -> None:
    d = ExtractedDoc("x.pdf", "pdf", ["p"], {})
    size, overlap = _chunk_params_for_doc(d)
    assert size == 1400
    assert overlap == 200


def test_split_sentences_ro_basic() -> None:
    s = "Ana merge acasă. Ion citește o carte. Următoarea propoziție."
    parts = _split_sentences_ro(s)
    assert len(parts) >= 2
    assert any("Ana" in p for p in parts)
    assert any("Ion" in p for p in parts)


def test_docs_to_chunks_scanned_uses_sentence_boundaries(monkeypatch) -> None:
    monkeypatch.setenv("RAG_CHUNK_BY_SENTENCES", "1")
    monkeypatch.setenv("RAG_CHUNK_CHARS_OCR", "500")
    body = " ".join(["Propoziție scurtă numărul unu.", "A doua propoziție pentru test.", "A treia."] * 6)
    doc = ExtractedDoc("s.pdf", "scanned_pdf", [body], {"ocr": True})
    texts, _, _ = docs_to_chunks(doc=doc)
    assert texts
    assert all(len(t) <= 520 for t in texts)


def test_docs_to_chunks_respects_scanned_chunk_cap() -> None:
    token = "word "
    long = token * 500
    doc = ExtractedDoc("s.pdf", "scanned_pdf", [long], {"ocr": True})
    texts, _, _ = docs_to_chunks(doc=doc)
    assert texts
    assert max(len(t) for t in texts) <= 1100


def test_resolve_ocrmypdf_executable_returns_str_or_none() -> None:
    from app.ocr_pdf import _resolve_ocrmypdf_executable

    p = _resolve_ocrmypdf_executable()
    assert p is None or (isinstance(p, str) and len(p) > 0)
