from __future__ import annotations

from typing import Any

from app import drive_google
from app.drive_organize import copy_items
from app.drive_settings import DriveSettings
from app.ingest import ingest_bytes_into_rag


def copy_drive_items_with_optional_rag(
    service,
    settings: DriveSettings,
    items: list[dict[str, str]],
    *,
    rag: Any,
    ingest_to_rag: bool,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = copy_items(service, settings, items)
    if not ingest_to_rag:
        return {"ok": True, "results": results, "rag_chunks": int(rag.count())}

    for res in results:
        if not res.get("ok"):
            continue
        copied_id = res.get("copied_file_id")
        if not copied_id:
            res["ingest"] = {"status": "skipped", "detail": "lipsește copied_file_id"}
            continue
        try:
            meta = (
                service.files()
                .get(
                    fileId=str(copied_id),
                    fields="name,mimeType",
                    supportsAllDrives=True,
                )
                .execute()
            )
            fname = str(meta.get("name") or res.get("name") or "document")
            mime = meta.get("mimeType")
            raw = drive_google.download_bytes(
                service,
                str(copied_id),
                mime_type=mime,
                max_bytes=24_000_000,
            )
        except Exception as e:  # noqa: BLE001
            res["ingest"] = {"status": "error", "detail": str(e), "chunks_added": 0}
            continue

        info = ingest_bytes_into_rag(
            rag,
            filename=fname,
            content=raw,
            mime_type=str(mime) if mime else None,
            extra_meta={"drive_file_id": str(copied_id), "origin": "google_drive"},
        )
        res["ingest"] = info

    return {"ok": True, "results": results, "rag_chunks": int(rag.count())}
