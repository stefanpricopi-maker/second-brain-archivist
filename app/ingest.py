from __future__ import annotations

import hashlib
import io
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pypdf import PdfReader


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


def _stable_id(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:32]


@dataclass(frozen=True)
class ExtractedDoc:
    source: str
    source_type: str
    pages: list[str]
    meta: dict[str, Any]


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

    from app.ocr_pdf import ocr_pdf_pages

    ocr_pages = ocr_pdf_pages(content=content)
    if not ocr_pages:
        raise ValueError("OCR: nu s-au putut citi paginile din PDF.")
    ocr_joined = sum(len(p or "") for p in ocr_pages)
    if ocr_joined < 8:
        raise ValueError(
            "OCR: text aproape gol. Verifică calitatea scanării, limba (OCR_LANG în .env) și că ai instalat "
            "datele de antrenament tesseract pentru limbile folosite."
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

        texts, metas, ids = docs_to_chunks(doc=doc)
        if not texts:
            return {
                "status": "error",
                "detail": "nu s-a extras text util (PDF scanat sau fișier gol?)",
                "chunks_added": 0,
            }
        for m in metas:
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


def docs_to_chunks(*, doc: ExtractedDoc) -> tuple[list[str], list[dict[str, Any]], list[str]]:
    texts: list[str] = []
    metas: list[dict[str, Any]] = []
    ids: list[str] = []
    for page_idx, page_text in enumerate(doc.pages, start=1):
        for chunk_idx, chunk in enumerate(_chunk_text(page_text), start=1):
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
    return texts, metas, ids

