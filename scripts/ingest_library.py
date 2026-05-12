from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from pypdf import PdfReader

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.ingest import docs_to_chunks, extract_epub  # noqa: E402
from app.rag import LibraryRAGIndex  # noqa: E402

load_dotenv()

LIBRARY_DIR = Path(os.getenv("LIBRARY_DIR", "./data/library")).resolve()
PUBLIC_NOTES_DIR = Path(os.getenv("PUBLIC_NOTES_DIR", "./knowledge/public")).resolve()
VECTORSTORE_DIR = Path(os.getenv("VECTORSTORE_DIR", "./data/vectorstore")).resolve()


def _chunk_text(text: str, *, chunk_size: int = 1400, overlap: int = 200) -> list[str]:
    text = " ".join(text.split())
    if not text:
        return []
    chunks: list[str] = []
    i = 0
    while i < len(text):
        chunk = text[i : i + chunk_size]
        chunks.append(chunk)
        i += max(1, chunk_size - overlap)
    return chunks


def _stable_id(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:32]


def _index_text_files(rag: LibraryRAGIndex, base: Path, label: str, globs: list[str]) -> int:
    n = 0
    if not base.exists():
        print(f"{label}: skip (missing): {base}")
        return 0
    for pattern in globs:
        for path in sorted(base.rglob(pattern)):
            if not path.is_file():
                continue
            rel = path.relative_to(base)
            text = path.read_text(encoding="utf-8", errors="replace")
            for chunk_idx, chunk in enumerate(_chunk_text(text), start=1):
                doc_key = f"{rel}|c{chunk_idx}"
                cid = _stable_id(doc_key)
                rag.add_texts(
                    ids=[cid],
                    texts=[chunk],
                    metadatas=[
                        {
                            "source": str(rel),
                            "chunk": chunk_idx,
                            "source_type": label,
                        }
                    ],
                )
                n += 1
            print(f"Indexed {label}: {rel}")
    return n


def _index_pdfs(rag: LibraryRAGIndex) -> int:
    n = 0
    if not LIBRARY_DIR.exists():
        print(f"Library dir does not exist (ok): {LIBRARY_DIR}")
        return 0
    pdfs = sorted([p for p in LIBRARY_DIR.rglob("*.pdf") if p.is_file()])
    for pdf_path in pdfs:
        reader = PdfReader(str(pdf_path))
        rel = pdf_path.relative_to(LIBRARY_DIR)
        for page_idx, page in enumerate(reader.pages, start=1):
            try:
                text = page.extract_text() or ""
            except Exception:
                text = ""
            for chunk_idx, chunk in enumerate(_chunk_text(text), start=1):
                doc_key = f"{rel}|p{page_idx}|c{chunk_idx}"
                cid = _stable_id(doc_key)
                rag.add_texts(
                    ids=[cid],
                    texts=[chunk],
                    metadatas=[
                        {
                            "source": str(rel),
                            "page": page_idx,
                            "chunk": chunk_idx,
                            "source_type": "pdf",
                        }
                    ],
                )
                n += 1
        print(f"Indexed PDF {rel} ({len(reader.pages)} pages)")
    return n


def _index_epubs(rag: LibraryRAGIndex) -> int:
    n = 0
    if not LIBRARY_DIR.exists():
        return 0
    for path in sorted([p for p in LIBRARY_DIR.rglob("*.epub") if p.is_file()]):
        rel = path.relative_to(LIBRARY_DIR)
        raw = path.read_bytes()
        try:
            doc = extract_epub(filename=str(rel), content=raw)
        except Exception as e:
            print(f"EPUB skip {rel}: {e}")
            continue
        texts, metas, ids = docs_to_chunks(doc=doc)
        if not texts:
            print(f"EPUB no text: {rel}")
            continue
        rag.add_texts(ids=ids, texts=texts, metadatas=metas)
        n += len(ids)
        print(f"Indexed EPUB {rel} ({doc.meta.get('chapter_count', '?')} chapters, {len(ids)} chunks)")
    return n


def main() -> None:
    rag = LibraryRAGIndex(persist_dir=VECTORSTORE_DIR)
    total = 0
    total += _index_pdfs(rag)
    total += _index_epubs(rag)
    total += _index_text_files(rag, LIBRARY_DIR, "library_txt", ["*.md", "*.txt"])
    total += _index_text_files(rag, PUBLIC_NOTES_DIR, "public_note", ["*.md"])

    if total == 0:
        raise SystemExit(
            f"No documents found. Add PDF/EPUB/MD/TXT under {LIBRARY_DIR} "
            f"and/or markdown under {PUBLIC_NOTES_DIR}."
        )
    print(f"Done. Indexed ~{total} chunks into {VECTORSTORE_DIR}")


if __name__ == "__main__":
    main()
