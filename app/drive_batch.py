"""Batch: citește un folder Drive și copiază fișierele în subfolderele bibliotecii după extensie."""

from __future__ import annotations

import time
from collections import deque
from typing import Any

from app import drive_google, drive_memory
from app.drive_extension_paths import extension_destination_segments
from app.drive_ingest import copy_drive_items_with_optional_rag
from app.drive_settings import DriveSettings


def gather_source_files(
    service,
    source_folder_id: str,
    *,
    recursive: bool,
    max_files: int,
) -> list[dict[str, Any]]:
    """
    Colectează metadate fișiere (non-folder) din `source_folder_id`.

    - `recursive=False`: doar copiii direcți (fișiere).
    - `recursive=True`: parcurgere în lățime prin toate subfolderele.
    """
    if max_files <= 0:
        return []
    if not recursive:
        found = drive_google.list_nonfolder_children(service, source_folder_id)
        return found[:max_files]

    out: list[dict[str, Any]] = []
    q: deque[str] = deque([source_folder_id])
    seen_folders: set[str] = set()
    while q and len(out) < max_files:
        folder_id = q.popleft()
        if folder_id in seen_folders:
            continue
        seen_folders.add(folder_id)
        for f in drive_google.list_nonfolder_children(service, folder_id):
            if len(out) >= max_files:
                return out
            out.append(f)
        for sub in drive_google.list_subfolders(service, folder_id):
            sid = sub.get("id")
            if sid and str(sid) not in seen_folders:
                q.append(str(sid))
    return out


def batch_auto_organize_from_folder(
    service,
    settings: DriveSettings,
    *,
    source_folder_id: str,
    recursive: bool,
    max_files: int,
    ingest_to_rag: bool,
    rag: Any,
    pause_sec: float = 0.06,
) -> dict[str, Any]:
    """
    Pentru fiecare fișier din sursă: extensie → subfolder bibliotecă, creează calea, copiază, opțional RAG.

    Sare peste `source_file_id` deja înregistrat în memoria de copieri.
    """
    if recursive and source_folder_id.strip() == settings.library_root_folder_id.strip():
        return {
            "ok": False,
            "detail": "Recursive pe rădăcina bibliotecii nu e permis (risc de bucle / duplicate).",
        }

    files = gather_source_files(
        service,
        source_folder_id,
        recursive=recursive,
        max_files=max_files,
    )
    skipped: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    ok_rows: list[dict[str, Any]] = []

    for f in files:
        fid = str(f.get("id") or "")
        name = str(f.get("name") or "file")
        mime = f.get("mimeType")
        if not fid:
            continue
        if mime == "application/vnd.google-apps.folder":
            continue
        state = drive_memory.load_state(settings.memory_path)
        if drive_memory.already_copied(state, fid):
            skipped.append({"file_id": fid, "file_name": name, "reason": "already_copied"})
            time.sleep(pause_sec)
            continue

        _label, segs = extension_destination_segments(name)
        try:
            leaf_id, created = drive_google.ensure_folder_path_under_root(
                service,
                library_root_folder_id=settings.library_root_folder_id,
                segments=segs,
            )
        except Exception as e:  # noqa: BLE001
            errors.append({"file_id": fid, "file_name": name, "detail": f"ensure_path: {e}"})
            time.sleep(pause_sec)
            continue

        try:
            batch_out = copy_drive_items_with_optional_rag(
                service,
                settings,
                [{"source_file_id": fid, "target_folder_id": leaf_id}],
                rag=rag,
                ingest_to_rag=ingest_to_rag,
            )
        except Exception as e:  # noqa: BLE001
            errors.append({"file_id": fid, "file_name": name, "detail": str(e)})
            time.sleep(pause_sec)
            continue

        res = (batch_out.get("results") or [{}])[0]
        if not res.get("ok"):
            errors.append(
                {
                    "file_id": fid,
                    "file_name": name,
                    "detail": str(res.get("detail") or "copy failed"),
                }
            )
        else:
            ok_rows.append(
                {
                    "file_id": fid,
                    "file_name": name,
                    "library_subpath": "/".join(segs),
                    "folders_created": created,
                    "copied_file_id": res.get("copied_file_id"),
                    "copied_web_link": res.get("copied_web_link"),
                }
            )
        time.sleep(pause_sec)

    return {
        "ok": True,
        "source_folder_id": source_folder_id,
        "recursive": recursive,
        "scanned_count": len(files),
        "copied_ok": len(ok_rows),
        "skipped_count": len(skipped),
        "errors_count": len(errors),
        "rag_chunks": int(rag.count()),
        "skipped_sample": skipped[:40],
        "errors_sample": errors[:80],
        "copied_sample": ok_rows[:40],
    }
