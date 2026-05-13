from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from app.ingest import (
    docs_to_chunks,
    extract_docx,
    extract_epub,
    extract_pdf,
    extract_pdf_for_voice_shelf,
    extract_text_like,
    save_upload,
)

ProgressCb = Callable[[dict[str, Any]], None]


def _mb_to_bytes(name: str, default_mb: int) -> int:
    try:
        mb = int(os.getenv(name, str(default_mb)))
    except ValueError:
        mb = default_mb
    return max(1, mb) * 1024 * 1024


MAX_MAIN_INGEST_BYTES = _mb_to_bytes("MAX_INGEST_FILE_MB", 64)
MAX_VOICE_INGEST_BYTES = _mb_to_bytes("MAX_VOICE_INGEST_FILE_MB", 64)


def _max_files(name: str, default: int) -> int:
    try:
        v = int(os.getenv(name, str(default)))
    except ValueError:
        v = default
    return max(1, min(200, v))


MAX_MAIN_FILES = _max_files("MAX_INGEST_FILES_PER_REQUEST", 40)
MAX_VOICE_FILES = _max_files("MAX_VOICE_INGEST_FILES_PER_REQUEST", 20)


def _replace_source_on_reupload() -> bool:
    return (os.getenv("INGEST_REPLACE_SOURCE_ON_REUPLOAD") or "true").strip().lower() in ("1", "true", "yes", "on")


def _sha256_hex(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _emit(progress: ProgressCb | None, payload: dict[str, Any]) -> None:
    if progress:
        progress(dict(payload))


def ingest_main_files(
    rag: Any,
    uploads_dir: Path,
    items: list[tuple[str, bytes]],
    *,
    dry_run: bool = False,
    progress: ProgressCb | None = None,
) -> dict[str, Any]:
    """
    items: (filename, raw_bytes).
    dry_run: doar validare (mărime, tip, hash) — fără scriere pe disc sau Chroma.
    """
    summaries: list[dict[str, Any]] = []
    added = 0
    n = max(1, len(items))
    replace_src = _replace_source_on_reupload()

    if len(items) > MAX_MAIN_FILES:
        return {
            "status": "error",
            "files": [
                {
                    "filename": "(cerere)",
                    "status": "error",
                    "detail": f"Prea multe fișiere într-o cerere (max {MAX_MAIN_FILES}).",
                }
            ],
            "added_chunks": 0,
            "rag_chunks": rag.count(),
            "dry_run": dry_run,
        }

    for idx, (name0, raw) in enumerate(items):
        name = (name0 or "upload").strip() or "upload"
        span = 100.0 / n
        base_pct = (idx / n) * 100.0
        _emit(
            progress,
            {
                "phase": "dry_validate" if dry_run else "ingest",
                "filename": name,
                "file_index": idx,
                "file_count": n,
                "percent": base_pct + 0.02 * span,
            },
        )

        if not raw:
            summaries.append({"filename": name, "status": "error", "detail": "empty"})
            _emit(progress, {"percent": base_pct + span, "filename": name})
            continue
        if len(raw) > MAX_MAIN_INGEST_BYTES:
            summaries.append(
                {
                    "filename": name,
                    "status": "error",
                    "detail": f"Fișier prea mare (max {MAX_MAIN_INGEST_BYTES // (1024 * 1024)} MiB).",
                    "size": len(raw),
                }
            )
            _emit(progress, {"percent": base_pct + span, "filename": name})
            continue

        h = _sha256_hex(raw)
        existing_sha = rag.get_bytes_sha_for_source(source=name)

        if existing_sha == h:
            summaries.append(
                {
                    "filename": name,
                    "status": "skipped_unchanged",
                    "bytes_sha256": h,
                    "detail": "Identic cu indexul curent (același conținut).",
                }
            )
            _emit(progress, {"percent": base_pct + span, "filename": name})
            continue

        ext = Path(name).suffix.lower()
        if dry_run:
            is_pdf = ext == ".pdf" or (len(raw) >= 4 and raw[:4] == b"%PDF")
            if ext == ".doc":
                summaries.append(
                    {
                        "filename": name,
                        "status": "error",
                        "bytes_sha256": h,
                        "detail": "format .doc (legacy) nu e suportat încă; convertește la .docx sau PDF.",
                        "size": len(raw),
                    }
                )
            elif is_pdf or ext in (".md", ".txt", ".docx", ".epub"):
                hint = "PDF" if is_pdf else ext
                summaries.append(
                    {
                        "filename": name,
                        "status": "would_ingest",
                        "bytes_sha256": h,
                        "detail": f"dry_run — nu s-a scris nimic; {hint} acceptat pentru indexare.",
                        "size": len(raw),
                    }
                )
            else:
                summaries.append(
                    {
                        "filename": name,
                        "status": "error",
                        "bytes_sha256": h,
                        "detail": f"tip neacceptat pentru indexare: {ext or '(no ext)'}",
                        "size": len(raw),
                    }
                )
            _emit(progress, {"percent": base_pct + span, "filename": name})
            continue

        if existing_sha is not None and existing_sha != h and replace_src:
            rag.delete_by_source(source=name)

        saved = save_upload(uploads_dir=uploads_dir, filename=name, content=raw)
        ext = saved.suffix.lower()
        try:
            if ext == ".pdf":
                doc = extract_pdf(filename=name, content=raw)
            elif ext in (".md", ".txt"):
                doc = extract_text_like(filename=name, content=raw, source_type=ext.lstrip("."))
            elif ext == ".docx":
                doc = extract_docx(filename=name, content=raw)
            elif ext == ".epub":
                doc = extract_epub(filename=name, content=raw)
            elif ext == ".doc":
                summaries.append(
                    {
                        "filename": name,
                        "status": "error",
                        "detail": "format .doc (legacy) nu e suportat încă; convertește la .docx sau PDF.",
                    }
                )
                _emit(progress, {"percent": base_pct + span, "filename": name})
                continue
            else:
                summaries.append(
                    {
                        "filename": name,
                        "status": "error",
                        "detail": f"unsupported file type: {ext or '(no ext)'}",
                    }
                )
                _emit(progress, {"percent": base_pct + span, "filename": name})
                continue

            doc.meta.setdefault("bytes_sha256", h)
            doc.meta["ingested_at"] = _utc_now_iso()

            texts, metas, ids = docs_to_chunks(doc=doc)
            for m in metas:
                m["bytes_sha256"] = h
                m.setdefault("ingested_at", doc.meta.get("ingested_at"))
            if not texts:
                summaries.append(
                    {
                        "filename": name,
                        "status": "error",
                        "detail": "nu s-a extras text util. Pentru scanări folosește tab-ul «Cărți & voce» (OCR) sau `POST /voice-library/ingest`.",
                        "saved_path": str(saved),
                        "bytes_sha256": h,
                    }
                )
                _emit(progress, {"percent": base_pct + span, "filename": name})
                continue

            _emit(progress, {"phase": "indexing", "filename": name, "percent": base_pct + 0.55 * span})
            rag.add_texts(ids=ids, texts=texts, metadatas=metas)
            added += len(ids)
            summaries.append(
                {
                    "filename": name,
                    "status": "ok",
                    "saved_path": str(saved),
                    "chunks_added": len(ids),
                    "source_type": doc.source_type,
                    "meta": doc.meta,
                    "bytes_sha256": h,
                }
            )
        except Exception as e:  # noqa: BLE001
            summaries.append({"filename": name, "status": "error", "detail": str(e), "saved_path": str(saved), "bytes_sha256": h})
        _emit(progress, {"percent": base_pct + span, "filename": name, "phase": "ingest"})

    return {
        "status": "ok",
        "files": summaries,
        "added_chunks": added,
        "rag_chunks": rag.count(),
        "dry_run": dry_run,
    }


def ingest_voice_pdf_batch(
    rag: Any,
    uploads_dir: Path,
    items: list[tuple[str, bytes]],
    *,
    book_label: str | None,
    force_ocr: str,
    dry_run: bool = False,
    progress: ProgressCb | None = None,
) -> dict[str, Any]:
    summaries: list[dict[str, Any]] = []
    added = 0
    n = max(1, len(items))
    replace_src = _replace_source_on_reupload()
    bl = (book_label or "").strip() or None

    if len(items) > MAX_VOICE_FILES:
        return {
            "status": "error",
            "files": [
                {
                    "filename": "(cerere)",
                    "status": "error",
                    "detail": f"Prea multe PDF-uri într-o cerere (max {MAX_VOICE_FILES}).",
                }
            ],
            "added_chunks": 0,
            "rag_chunks": rag.count(),
            "dry_run": dry_run,
        }

    for idx, (name0, raw) in enumerate(items):
        name = (name0 or "upload").strip() or "upload"
        span = 100.0 / n
        base_pct = (idx / n) * 100.0
        _emit(
            progress,
            {
                "phase": "dry_validate" if dry_run else "ingest",
                "filename": name,
                "file_index": idx,
                "file_count": n,
                "percent": base_pct + 0.02 * span,
            },
        )

        if not raw:
            summaries.append({"filename": name, "status": "error", "detail": "empty"})
            _emit(progress, {"percent": base_pct + span, "filename": name})
            continue
        if len(raw) > MAX_VOICE_INGEST_BYTES:
            summaries.append(
                {
                    "filename": name,
                    "status": "error",
                    "detail": f"Fișier prea mare (max {MAX_VOICE_INGEST_BYTES // (1024 * 1024)} MiB).",
                    "size": len(raw),
                }
            )
            _emit(progress, {"percent": base_pct + span, "filename": name})
            continue
        if not name.lower().endswith(".pdf"):
            summaries.append(
                {
                    "filename": name,
                    "status": "error",
                    "detail": "În «Cărți & voce» acceptăm doar .pdf (scanat sau text).",
                }
            )
            _emit(progress, {"percent": base_pct + span, "filename": name})
            continue

        h = _sha256_hex(raw)
        existing_sha = rag.get_bytes_sha_for_source(source=name)
        if existing_sha == h:
            summaries.append(
                {
                    "filename": name,
                    "status": "skipped_unchanged",
                    "bytes_sha256": h,
                    "detail": "Identic cu indexul curent (același conținut).",
                }
            )
            _emit(progress, {"percent": base_pct + span, "filename": name})
            continue

        if dry_run:
            summaries.append(
                {
                    "filename": name,
                    "status": "would_ingest",
                    "bytes_sha256": h,
                    "detail": "dry_run — nu s-a rulat OCR/indexare.",
                    "size": len(raw),
                }
            )
            _emit(progress, {"percent": base_pct + span, "filename": name})
            continue

        if existing_sha is not None and existing_sha != h and replace_src:
            rag.delete_by_source(source=name)

        saved = save_upload(uploads_dir=uploads_dir, filename=name, content=raw)
        try:
            doc = extract_pdf_for_voice_shelf(
                filename=name,
                content=raw,
                book_label=bl,
                force_ocr=(force_ocr or "auto").strip(),
            )
            doc.meta.setdefault("bytes_sha256", h)
            doc.meta["ingested_at"] = _utc_now_iso()
            texts, metas, ids = docs_to_chunks(doc=doc)
            for m in metas:
                m["bytes_sha256"] = h
                m.setdefault("ingested_at", doc.meta.get("ingested_at"))
            if not texts:
                summaries.append(
                    {
                        "filename": name,
                        "status": "error",
                        "detail": "nu s-au putut genera fragmente după OCR/extragere.",
                        "saved_path": str(saved),
                        "bytes_sha256": h,
                    }
                )
                _emit(progress, {"percent": base_pct + span, "filename": name})
                continue
            _emit(progress, {"phase": "ocr_index", "filename": name, "percent": base_pct + 0.55 * span})
            rag.add_texts(ids=ids, texts=texts, metadatas=metas)
            added += len(ids)
            summaries.append(
                {
                    "filename": name,
                    "status": "ok",
                    "saved_path": str(saved),
                    "chunks_added": len(ids),
                    "source_type": doc.source_type,
                    "meta": doc.meta,
                    "bytes_sha256": h,
                }
            )
        except Exception as e:  # noqa: BLE001
            summaries.append({"filename": name, "status": "error", "detail": str(e), "saved_path": str(saved), "bytes_sha256": h})
        _emit(progress, {"percent": base_pct + span, "filename": name, "phase": "ingest"})

    return {
        "status": "ok",
        "files": summaries,
        "added_chunks": added,
        "rag_chunks": rag.count(),
        "dry_run": dry_run,
    }
