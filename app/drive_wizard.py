"""Flux wizard: plasare automată după încărcare (extensie → subfolder bibliotecă)."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from app import drive_google, drive_memory
from app.drive_extension_paths import extension_destination_segments
from app.drive_ingest import copy_drive_items_with_optional_rag
from app.drive_organize import library_folder_options
from app.drive_settings import DriveSettings

log = logging.getLogger(__name__)

# Aliniat cu `WizardAutoPlaceRequest` / UI (`AUTO_PLACE_MAX_IDS` în static/js/app.js).
WIZARD_AUTO_PLACE_MAX_IDS = 120


def chunk_source_file_ids(
    source_file_ids: list[str],
    *,
    max_per_chunk: int = WIZARD_AUTO_PLACE_MAX_IDS,
) -> list[list[str]]:
    """Împarte lista de ID-uri în bucăți de cel mult `max_per_chunk` (cereri HTTP separate)."""
    cleaned = [(x or "").strip() for x in source_file_ids if (x or "").strip()]
    step = max(1, int(max_per_chunk))
    return [cleaned[i : i + step] for i in range(0, len(cleaned), step)]


def merge_wizard_auto_place_payloads(parts: list[dict[str, Any]]) -> dict[str, Any]:
    """Unește răspunsuri `auto_place_uploaded_file_ids` din mai multe runde (aceeași logică ca UI-ul)."""
    if not parts:
        return {
            "ok": True,
            "folder_options": [],
            "succeeded": [],
            "needs_manual": [],
            "skipped": [],
            "rag_chunks": 0,
        }
    succeeded: list[dict[str, Any]] = []
    needs_manual: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    folder_options: list[dict[str, Any]] = []
    rag_chunks = 0
    ok_all = True
    for p in parts:
        if not p.get("ok", True):
            ok_all = False
        succeeded.extend(p.get("succeeded") or [])
        needs_manual.extend(p.get("needs_manual") or [])
        skipped.extend(p.get("skipped") or [])
        fo = p.get("folder_options") or []
        if fo:
            folder_options = list(fo)
        if isinstance(p.get("rag_chunks"), int):
            rag_chunks = int(p["rag_chunks"])
    return {
        "ok": ok_all,
        "folder_options": folder_options,
        "succeeded": succeeded,
        "needs_manual": needs_manual,
        "skipped": skipped,
        "rag_chunks": rag_chunks,
    }


def _needs_manual_no_extension(file_name: str) -> bool:
    """Fără sufix pe nume nu putem aplica regulile pe extensie — utilizatorul alege folderul."""
    return Path(file_name or "").suffix == ""


def _needs_manual_google_native(mime: str | None) -> bool:
    return bool(mime and str(mime).startswith("application/vnd.google-apps."))


def auto_place_uploaded_file_ids(
    service,
    settings: DriveSettings,
    *,
    source_file_ids: list[str],
    ingest_to_rag: bool,
    rag: Any,
) -> dict[str, Any]:
    """
    Pentru fiecare ID încărcat în Stage: extensie → cale bibliotecă, copiere.
    Eșecuri / fără extensie / Google native → `needs_manual` cu același set de opțiuni de foldere.
    """
    t0 = time.perf_counter()
    folder_options = library_folder_options(service, settings.library_root_folder_id)
    succeeded: list[dict[str, Any]] = []
    needs_manual: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for raw_id in source_file_ids:
        fid = (raw_id or "").strip()
        if not fid:
            continue
        state = drive_memory.load_state(settings.memory_path)
        if drive_memory.already_copied(state, fid):
            skipped.append({"file_id": fid, "reason": "already_copied"})
            continue

        try:
            meta = (
                service.files()
                .get(fileId=fid, fields="id,name,mimeType", supportsAllDrives=True)
                .execute()
            )
            name = str(meta.get("name") or "file")
            mime = meta.get("mimeType")
        except Exception as e:  # noqa: BLE001
            needs_manual.append(
                {
                    "file_id": fid,
                    "file_name": fid,
                    "detail": f"Nu pot citi metadata: {e}",
                }
            )
            continue

        if _needs_manual_google_native(mime if isinstance(mime, str) else None):
            needs_manual.append(
                {
                    "file_id": fid,
                    "file_name": name,
                    "detail": "Fișier Google Docs/Sheets etc. — alege manual folderul (sau exportă ca PDF în Drive).",
                }
            )
            continue

        if _needs_manual_no_extension(name):
            needs_manual.append(
                {
                    "file_id": fid,
                    "file_name": name,
                    "detail": "Lipsește extensia din nume — nu putem aplica regulile PDF/Documente/Afise/Powerpoint.",
                }
            )
            continue

        _label, segs = extension_destination_segments(name)
        try:
            leaf_id, created = drive_google.ensure_folder_path_under_root(
                service,
                library_root_folder_id=settings.library_root_folder_id,
                segments=segs,
            )
        except Exception as e:  # noqa: BLE001
            needs_manual.append(
                {
                    "file_id": fid,
                    "file_name": name,
                    "detail": f"Nu pot crea subfoldere: {e}",
                }
            )
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
            needs_manual.append(
                {
                    "file_id": fid,
                    "file_name": name,
                    "detail": str(e),
                }
            )
            continue

        res = (batch_out.get("results") or [{}])[0]
        if not res.get("ok"):
            needs_manual.append(
                {
                    "file_id": fid,
                    "file_name": name,
                    "detail": str(res.get("detail") or "Copiere eșuată"),
                }
            )
            continue

        succeeded.append(
            {
                "file_id": fid,
                "file_name": name,
                "library_subpath": "/".join(segs),
                "folders_created": created,
                "copied_file_id": res.get("copied_file_id"),
                "copied_web_link": res.get("copied_web_link"),
                "target_folder_name": res.get("target_folder_name"),
            }
        )

    elapsed_ms = (time.perf_counter() - t0) * 1000
    log.info(
        "drive_wizard.auto_place ids_in=%s succeeded=%s manual=%s skipped=%s ms=%.1f ingest_rag=%s",
        len(source_file_ids),
        len(succeeded),
        len(needs_manual),
        len(skipped),
        elapsed_ms,
        ingest_to_rag,
    )
    return {
        "ok": True,
        "folder_options": folder_options,
        "succeeded": succeeded,
        "needs_manual": needs_manual,
        "skipped": skipped,
        "rag_chunks": int(rag.count()),
    }
