from __future__ import annotations

import hashlib
import io
import os
import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pypdf import PdfReader


def _dedupe_consecutive_lines(text: str) -> str:
    """Elimină linii identice consecutive — frecvent la anteturi / artefacte OCR."""
    lines = (text or "").splitlines()
    out: list[str] = []
    prev: str | None = None
    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        if prev is not None and s == prev:
            continue
        out.append(s)
        prev = s
    return "\n".join(out)


def _normalize_scanned_page_text(text: str) -> str:
    t = _dedupe_consecutive_lines(text)
    return " ".join(t.split())


def _chunk_text(text: str, *, chunk_size: int = 1400, overlap: int = 200) -> list[str]:
    text = " ".join((text or "").split())
    if not text:
        return []
    chunks: list[str] = []
    i = 0
    while i < len(text):
        chunks.append(text[i : i + chunk_size])
        i += max(1, chunk_size - overlap)
    return chunks


# După punctuație de sfârșit de propoziție, urmată de spații și început plauzibil de frază (ro + cifre).
_SPLIT_SENTENCES = re.compile(
    r'(?<=[.!?…])(?:[\"\'»\)\]])*\s+(?=(?:[\"„"\'«(])*[A-ZĂÂÎȘȚa-zăâîșț0-9])'
)


def _split_sentences_ro(text: str) -> list[str]:
    raw = " ".join((text or "").split())
    if len(raw) < 2:
        return []
    parts = _SPLIT_SENTENCES.split(raw)
    out = [p.strip() for p in parts if p.strip()]
    return out if out else [raw]


def _explode_oversized_sentences(sents: list[str], chunk_size: int) -> list[str]:
    out: list[str] = []
    for s in sents:
        if len(s) <= chunk_size:
            out.append(s)
        else:
            out.extend(_chunk_text(s, chunk_size=chunk_size, overlap=0))
    return out


def _chunk_text_by_sentences(text: str, *, chunk_size: int, overlap: int) -> list[str]:
    """Grupare pe propoziții până la chunk_size; parametrul overlap e ignorat (rezervat)."""
    del overlap
    sents = _explode_oversized_sentences(_split_sentences_ro(text), chunk_size)
    if not sents:
        return []
    if len(sents) == 1:
        return _chunk_text(sents[0], chunk_size=chunk_size, overlap=0)
    chunks: list[str] = []
    start = 0
    while start < len(sents):
        parts: list[str] = []
        total = 0
        pos = start
        while pos < len(sents):
            s = sents[pos]
            sep = 1 if parts else 0
            if total + sep + len(s) > chunk_size and parts:
                break
            if total + sep + len(s) > chunk_size and not parts:
                parts.append(s[:chunk_size])
                pos += 1
                break
            parts.append(s)
            total += sep + len(s)
            pos += 1
        chunks.append(" ".join(parts))
        start = pos
    return chunks if chunks else _chunk_text(text, chunk_size=chunk_size, overlap=0)


def _stable_id(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:32]


@dataclass(frozen=True)
class ExtractedDoc:
    source: str
    source_type: str
    pages: list[str]
    meta: dict[str, Any]


def _chunk_params_for_doc(doc: ExtractedDoc) -> tuple[int, int]:
    """Dimensiuni fragment: PDF scanat/OCR mai scurt; EPUB ușor mai lung pentru flux narativ."""
    base = int(os.getenv("RAG_CHUNK_CHARS") or "1400")
    overlap = int(os.getenv("RAG_CHUNK_OVERLAP") or "200")
    if doc.source_type == "epub":
        base = min(2000, int(base * 1.12))
        overlap = min(280, int(overlap * 1.15))
    if doc.source_type == "scanned_pdf" or doc.meta.get("ocr"):
        o_sz = int(os.getenv("RAG_CHUNK_CHARS_OCR") or "1100")
        o_ov = int(os.getenv("RAG_CHUNK_OVERLAP_OCR") or "160")
        base = min(base, max(500, o_sz))
        overlap = min(overlap, max(80, o_ov))
    base = max(400, min(4000, base))
    overlap = max(0, min(base // 2, overlap))
    return base, overlap


def _sentence_chunking_enabled_for(doc: ExtractedDoc) -> bool:
    if not (
        doc.source_type == "scanned_pdf"
        or doc.meta.get("ocr")
        or doc.meta.get("scan_derived")
    ):
        return False
    v = (os.getenv("RAG_CHUNK_BY_SENTENCES") or "1").strip().lower()
    return v not in ("0", "false", "no", "off")


PDF_MIN_TEXT_CHARS = 80


def extract_pdf(*, filename: str, content: bytes) -> ExtractedDoc:
    reader = PdfReader(io.BytesIO(content))
    pages: list[str] = []
    for p in reader.pages:
        try:
            pages.append((p.extract_text() or "").strip())
        except Exception:
            pages.append("")
    return ExtractedDoc(
        source=filename,
        source_type="pdf",
        pages=pages,
        meta={"page_count": len(pages)},
    )


def _pdf_text_char_count(doc: ExtractedDoc) -> int:
    return sum(len(p or "") for p in doc.pages)


def extract_pdf_for_voice_shelf(
    *,
    filename: str,
    content: bytes,
    book_label: str | None,
    force_ocr: str,
) -> ExtractedDoc:
    """
    Flux «cărți scanate»: încearcă text PDF; dacă e gol/scurt sau `force_ocr=true`, folosește OCR (Tesseract).
    `force_ocr`: "auto" | "true" | "false".
    """
    label = (book_label or "").strip() or None
    mode = (force_ocr or "auto").strip().lower()
    if mode not in ("auto", "true", "false"):
        mode = "auto"

    base = extract_pdf(filename=filename, content=content)
    text_n = _pdf_text_char_count(base)

    use_ocr = mode == "true" or (mode == "auto" and text_n < PDF_MIN_TEXT_CHARS)
    if mode == "false":
        use_ocr = False

    meta_base: dict[str, Any] = {"voice_shelf": True, "page_count": len(base.pages)}
    if label:
        meta_base["book_label"] = label

    if not use_ocr:
        if text_n < PDF_MIN_TEXT_CHARS:
            raise ValueError(
                "PDF-ul pare scanat (foarte puțin text extras). Bifează OCR sau setează force_ocr=true "
                "și asigură-te că Tesseract + poppler sunt instalate."
            )
        return ExtractedDoc(
            source=base.source,
            source_type=base.source_type,
            pages=base.pages,
            meta=meta_base,
        )

    from app.ocr_pdf import ocr_pdf_pages, try_run_ocrmypdf

    content_for_pipeline = content
    refined_pdf = try_run_ocrmypdf(content=content, lang=os.getenv("OCR_LANG"))
    if refined_pdf:
        content_for_pipeline = refined_pdf
    layered = extract_pdf(filename=filename, content=content_for_pipeline)
    layered_n = _pdf_text_char_count(layered)
    if layered_n >= PDF_MIN_TEXT_CHARS:
        meta = dict(meta_base)
        meta["ocr_engine"] = "ocrmypdf"
        meta["scan_derived"] = True
        meta["page_count"] = len(layered.pages)
        return ExtractedDoc(
            source=base.source,
            source_type="pdf",
            pages=layered.pages,
            meta=meta,
        )

    ocr_pages = ocr_pdf_pages(content=content_for_pipeline)
    if not ocr_pages:
        raise ValueError("OCR: nu s-au putut citi paginile din PDF.")
    ocr_joined = sum(len(p or "") for p in ocr_pages)
    if ocr_joined < 8:
        raise ValueError(
            "OCR: text aproape gol. Verifică calitatea scanării; pe macOS: `brew install tesseract-lang` (română `ron`). "
            "Implicit folosim `OCR_LANG=ron`; pentru mixt ro+en pune în `.env` `OCR_LANG=ron+eng`."
        )
    meta = dict(meta_base)
    meta["ocr"] = True
    meta["page_count"] = len(ocr_pages)
    return ExtractedDoc(
        source=base.source,
        source_type="scanned_pdf",
        pages=ocr_pages,
        meta=meta,
    )


def extract_text_like(*, filename: str, content: bytes, source_type: str) -> ExtractedDoc:
    text = content.decode("utf-8", errors="replace")
    return ExtractedDoc(
        source=filename,
        source_type=source_type,
        pages=[text],
        meta={},
    )


def extract_docx(*, filename: str, content: bytes) -> ExtractedDoc:
    from docx import Document  # python-docx

    doc = Document(io.BytesIO(content))
    text = "\n".join((p.text or "") for p in doc.paragraphs).strip()
    return ExtractedDoc(
        source=filename,
        source_type="docx",
        pages=[text],
        meta={},
    )


def _epub_html_to_text(html: str) -> str:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return soup.get_text("\n", strip=True)


def extract_epub(*, filename: str, content: bytes) -> ExtractedDoc:
    import ebooklib
    from ebooklib import epub

    book = epub.read_epub(io.BytesIO(content))
    dc_title = book.get_metadata("DC", "title")
    title = (dc_title[0][0] if dc_title else None) or filename
    dc_lang = book.get_metadata("DC", "language")
    lang = dc_lang[0][0] if dc_lang else None
    dc_creators = book.get_metadata("DC", "creator")
    author_list = [c[0] for c in dc_creators] if dc_creators else []

    pages: list[str] = []

    def push_item(item: Any) -> None:
        if item is None or item.get_type() != ebooklib.ITEM_DOCUMENT:
            return
        name_lower = (item.get_name() or "").lower()
        if name_lower.endswith("nav.xhtml") or name_lower.endswith("/nav.xhtml"):
            return
        try:
            raw = item.get_content()
        except Exception:
            return
        if not raw:
            return
        blob = raw if isinstance(raw, bytes) else str(raw).encode("utf-8", errors="replace")
        html = blob.decode("utf-8", errors="replace")
        text = _epub_html_to_text(html)
        if len(text.strip()) < 8:
            return
        pages.append(text)

    for ref in book.spine:
        item_id = ref[0] if isinstance(ref, tuple) else ref
        push_item(book.get_item_with_id(item_id))

    if not pages:
        for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            push_item(item)

    meta: dict[str, Any] = {"title": title, "chapter_count": len(pages)}
    if lang:
        meta["language"] = lang
    if author_list:
        meta["authors"] = ", ".join(author_list)

    return ExtractedDoc(
        source=filename,
        source_type="epub",
        pages=pages,
        meta=meta,
    )


def save_upload(*, uploads_dir: Path, filename: str, content: bytes) -> Path:
    uploads_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    safe = "".join(ch for ch in filename if ch.isalnum() or ch in (" ", "-", "_", ".", "(", ")")).strip()[:180] or "upload"
    path = uploads_dir / f"{ts}__{uuid.uuid4().hex[:8]}__{safe}"
    path.write_bytes(content)
    return path


def ingest_bytes_into_rag(
    rag: Any,
    *,
    filename: str,
    content: bytes,
    mime_type: str | None = None,
    extra_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Indexează conținut brut în colecția RAG (același flux ca upload-ul HTTP).
    Folosit după copiere din Google Drive. `rag` trebuie să aibă add_texts(ids=..., texts=..., metadatas=...).
    """
    name = (filename or "upload").strip() or "upload"
    ext = Path(name).suffix.lower()
    mt = (mime_type or "").lower()
    extra = {k: v for k, v in (extra_meta or {}).items() if v is not None}

    try:
        if ext == ".pdf" or mt == "application/pdf":
            doc = extract_pdf(filename=name, content=content)
        elif ext in (".md", ".txt") or mt in ("text/markdown", "text/plain"):
            st = "md" if ext == ".md" or mt == "text/markdown" else "txt"
            doc = extract_text_like(filename=name, content=content, source_type=st)
        elif ext == ".docx" or mt == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            doc = extract_docx(filename=name, content=content)
        elif ext == ".doc" or mt == "application/msword":
            return {
                "status": "error",
                "detail": "format .doc (legacy) nu e suportat; convertește la .docx sau PDF.",
                "chunks_added": 0,
            }
        elif mt.startswith("application/vnd.google-apps."):
            # Fișiere exportate deja ca text/csv de către Drive API.
            doc = extract_text_like(filename=name, content=content, source_type="txt")
        elif ext == ".epub" or mt in ("application/epub+zip", "application/epub"):
            doc = extract_epub(filename=name, content=content)
        elif ext == "" and len(content) >= 4 and content[:4] == b"%PDF":
            doc = extract_pdf(filename=name or "document.pdf", content=content)
        else:
            return {
                "status": "error",
                "detail": f"tip neacceptat pentru RAG: ext={ext or '(none)'} mime={mt or '(none)'}",
                "chunks_added": 0,
            }

        h = hashlib.sha256(content).hexdigest()
        ts = datetime.now(timezone.utc).isoformat()
        doc.meta.setdefault("bytes_sha256", h)
        doc.meta["ingested_at"] = ts
        texts, metas, ids = docs_to_chunks(doc=doc)
        if not texts:
            return {
                "status": "error",
                "detail": "nu s-a extras text util (PDF scanat sau fișier gol?)",
                "chunks_added": 0,
            }
        for m in metas:
            m["bytes_sha256"] = h
            m.setdefault("ingested_at", ts)
            m.update(extra)
        rag.add_texts(ids=ids, texts=texts, metadatas=metas)
        return {
            "status": "ok",
            "chunks_added": len(ids),
            "source_type": doc.source_type,
            "rag_chunks": int(rag.count()),
        }
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "detail": str(e), "chunks_added": 0}


def _dedupe_adjacent_identical_chunks(
    texts: list[str], metas: list[dict[str, Any]], ids: list[str]
) -> tuple[list[str], list[dict[str, Any]], list[str]]:
    """Elimină fragmente consecutive cu text normalizat identic (artefacte OCR / antete repetate)."""
    if not texts:
        return texts, metas, ids
    out_t: list[str] = []
    out_m: list[dict[str, Any]] = []
    out_i: list[str] = []
    prev_norm: str | None = None
    for t, m, i in zip(texts, metas, ids):
        n = " ".join((t or "").split())
        if n and prev_norm is not None and n == prev_norm:
            continue
        prev_norm = n if n else None
        out_t.append(t)
        out_m.append(m)
        out_i.append(i)
    return out_t, out_m, out_i


def docs_to_chunks(*, doc: ExtractedDoc) -> tuple[list[str], list[dict[str, Any]], list[str]]:
    texts: list[str] = []
    metas: list[dict[str, Any]] = []
    ids: list[str] = []
    cs, ov = _chunk_params_for_doc(doc)
    scanned_noise = doc.source_type == "scanned_pdf" or bool(doc.meta.get("ocr"))
    sentence_mode = _sentence_chunking_enabled_for(doc)
    for page_idx, page_text in enumerate(doc.pages, start=1):
        page_work = (
            _normalize_scanned_page_text(page_text) if scanned_noise else " ".join((page_text or "").split())
        )
        if sentence_mode:
            pieces = _chunk_text_by_sentences(page_work, chunk_size=cs, overlap=ov)
        else:
            pieces = _chunk_text(page_work, chunk_size=cs, overlap=ov)
        for chunk_idx, chunk in enumerate(pieces, start=1):
            key = f"{doc.source}|p{page_idx}|c{chunk_idx}|{doc.source_type}"
            ids.append(_stable_id(key))
            texts.append(chunk)
            md: dict[str, Any] = {
                "source": doc.source,
                "source_type": doc.source_type,
                "chunk": chunk_idx,
                **(doc.meta or {}),
            }
            if doc.source_type in ("pdf", "scanned_pdf"):
                md["page"] = page_idx
            elif doc.source_type == "epub":
                md["chapter"] = page_idx
            metas.append({k: v for k, v in md.items() if v is not None})
    texts, metas, ids = _dedupe_adjacent_identical_chunks(texts, metas, ids)
    return texts, metas, ids

