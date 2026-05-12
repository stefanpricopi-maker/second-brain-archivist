#!/usr/bin/env python3
"""
Batch Drive: citește un folder (implicit Stage), fișier cu fișier, copiază în bibliotecă după extensie.

Reguli de foldere: .pdf→PDF, .doc/.docx→Documente, imagini→Afise, .ppt/.pptx→Powerpoint, rest→Altele.

Exemple (din rădăcina proiectului, cu venv activat):

  # doar numără ce ar fi procesat (fără copiere)
  python scripts/drive_batch_auto_organize.py --dry-run

  # toate fișierele din Stage (non-recursiv), fără RAG
  python scripts/drive_batch_auto_organize.py

  # alt folder sursă + subfoldere + max 5000 fișiere + indexare RAG după copiere
  python scripts/drive_batch_auto_organize.py --folder-id FOLDER_ID --recursive --max-files 5000 --ingest-rag

Raport JSON complet: data/drive/batch_last_report.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")

from app.drive_batch import batch_auto_organize_from_folder, gather_source_files  # noqa: E402
from app.drive_google import drive_service, load_credentials  # noqa: E402
from app.drive_settings import load_drive_settings  # noqa: E402
from app.rag import LibraryRAGIndex  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch: organizează fișiere Drive după extensie.")
    parser.add_argument(
        "--folder-id",
        default="",
        help="ID folder sursă în Drive. Gol = GOOGLE_DRIVE_STAGE_FOLDER_ID din .env.",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Include toate subfolderele (BFS). Nu combina cu rădăcina bibliotecii.",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=50_000,
        help="Număr maxim de fișiere de procesat (implicit 50000).",
    )
    parser.add_argument(
        "--ingest-rag",
        action="store_true",
        help="După fiecare copiere reușită, adaugă în Chroma (mai lent).",
    )
    parser.add_argument(
        "--pause",
        type=float,
        default=0.06,
        help="Secunde pauză între fișiere (implicit 0.06).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Doar listează fișierele găsite, fără copiere.",
    )
    args = parser.parse_args()

    settings = load_drive_settings(PROJECT_ROOT)
    if not settings:
        raise SystemExit(
            "Drive nu e configurat: setează GOOGLE_DRIVE_STAGE_FOLDER_ID și "
            "GOOGLE_DRIVE_LIBRARY_ROOT_FOLDER_ID în .env."
        )

    creds = load_credentials(
        client_secret_path=settings.client_secret_path,
        token_path=settings.token_path,
    )
    svc = drive_service(creds)
    src = (args.folder_id or "").strip() or settings.stage_folder_id

    if args.dry_run:
        files = gather_source_files(
            svc,
            src,
            recursive=args.recursive,
            max_files=args.max_files,
        )
        preview = {
            "source_folder_id": src,
            "recursive": args.recursive,
            "scanned_count": len(files),
            "sample": [{"id": f.get("id"), "name": f.get("name")} for f in files[:30]],
        }
        print(json.dumps(preview, ensure_ascii=False, indent=2))
        return

    vs = Path(os.getenv("VECTORSTORE_DIR", str(PROJECT_ROOT / "data" / "vectorstore"))).resolve()
    rag = LibraryRAGIndex(persist_dir=vs)

    out = batch_auto_organize_from_folder(
        svc,
        settings,
        source_folder_id=src,
        recursive=args.recursive,
        max_files=args.max_files,
        ingest_to_rag=args.ingest_rag,
        rag=rag,
        pause_sec=args.pause,
    )

    if not out.get("ok"):
        raise SystemExit(out.get("detail") or "Eșec batch.")

    report_path = PROJECT_ROOT / "data" / "drive" / "batch_last_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = {
        "ok": out.get("ok"),
        "scanned_count": out.get("scanned_count"),
        "copied_ok": out.get("copied_ok"),
        "skipped_count": out.get("skipped_count"),
        "errors_count": out.get("errors_count"),
        "rag_chunks": out.get("rag_chunks"),
        "report_file": str(report_path),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
