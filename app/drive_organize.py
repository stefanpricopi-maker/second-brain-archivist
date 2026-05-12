from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from openai import OpenAI

from app import drive_google, drive_memory
from app.drive_extension_paths import extension_destination_segments
from app.drive_settings import DriveSettings


def _text_preview(raw: bytes, limit: int = 3500) -> str:
    return raw.decode("utf-8", errors="replace")[:limit]


def library_folder_options(service, library_root_id: str) -> list[dict[str, str]]:
    subs = drive_google.list_subfolders(service, library_root_id)
    opts: list[dict[str, str]] = [{"id": library_root_id, "name": "(root bibliotecă)"}]
    for f in subs:
        fid = f.get("id")
        if not fid:
            continue
        opts.append({"id": str(fid), "name": str(f.get("name") or "")})
    return opts


def _simple_suggest(name: str, preview: str, folder_options: list[dict[str, str]]) -> str:
    blob = f"{name} {preview}".lower()
    for opt in folder_options[1:]:
        oname = (opt.get("name") or "").lower().strip()
        if oname and oname in blob:
            return opt["id"]
    return folder_options[0]["id"]


def _llm_decisions(
    client: OpenAI,
    model: str,
    *,
    folder_options: list[dict[str, str]],
    placement_summaries: list[dict[str, Any]],
    file_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    payload = {
        "folders": folder_options,
        "previous_placements": placement_summaries,
        "new_files": [
            {
                "file_id": r["file_id"],
                "file_name": r["file_name"],
                "preview": (r.get("preview") or "")[:2500],
            }
            for r in file_rows
        ],
    }
    user_blob = json.dumps(payload, ensure_ascii=False)
    if len(user_blob) > 120_000:
        user_blob = user_blob[:120_000] + "\n…(truncated)"

    r = client.chat.completions.create(
        model=model,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "You classify personal library documents. Each new file must map to exactly one "
                    "`target_folder_id` from `folders[].id`. Return JSON: "
                    '{"decisions":[{"file_id":string,"target_folder_id":string,"needs_user":bool,"reason":string}]}. '
                    "Set `needs_user` true if ambiguous or weak match. "
                    "Use `previous_placements` patterns when filenames/previews are similar."
                ),
            },
            {"role": "user", "content": user_blob},
        ],
    )
    raw = (r.choices[0].message.content or "{}").strip()
    data = json.loads(raw)
    return list(data.get("decisions") or [])


def propose_stage(
    service,
    settings: DriveSettings,
    *,
    openai_client: OpenAI | None,
    openai_model: str,
) -> dict[str, Any]:
    state = drive_memory.load_state(settings.memory_path)
    folder_options = library_folder_options(service, settings.library_root_folder_id)
    valid_ids = {o["id"] for o in folder_options}

    files = drive_google.list_nonfolder_children(service, settings.stage_folder_id)
    pending = [f for f in files if not drive_memory.already_copied(state, str(f["id"]))]

    placement_summaries: list[dict[str, Any]] = []
    for p in (state.get("placements") or [])[-24:]:
        placement_summaries.append(
            {
                "source_name": p.get("source_name"),
                "preview": str(p.get("preview") or "")[:900],
                "target_folder_id": p.get("target_folder_id"),
                "target_folder_name": p.get("target_folder_name"),
            }
        )

    rows: list[dict[str, Any]] = []
    for f in pending:
        fid = str(f["id"])
        name = str(f.get("name") or "unknown")
        mime = f.get("mimeType")
        try:
            raw = drive_google.download_bytes(service, fid, mime_type=mime, max_bytes=600_000)
            preview = _text_preview(raw, 4000)
        except Exception as e:  # noqa: BLE001
            preview = f"(preview indisponibil: {e})"
        rows.append({"file_id": fid, "file_name": name, "mime_type": mime, "preview": preview})

    n_hist = len(state.get("placements") or [])
    auto_phase = n_hist >= settings.min_auto and openai_client is not None
    decisions_out: list[dict[str, Any]] = []

    if not rows:
        return {
            "ok": True,
            "phase": "auto" if auto_phase else "bootstrap",
            "library_placements_total": n_hist,
            "min_auto": settings.min_auto,
            "theme_paths_enabled": settings.theme_paths_enabled,
            "folder_options": folder_options,
            "files_in_stage_pending": [],
            "decisions": [],
            "message": "Nu sunt fișiere noi în Stage (sau toate au fost deja copiate în bibliotecă).",
        }

    if not auto_phase:
        for r in rows:
            sug = _simple_suggest(r["file_name"], r["preview"], folder_options)
            decisions_out.append(
                {
                    "file_id": r["file_id"],
                    "file_name": r["file_name"],
                    "suggested_target_folder_id": sug,
                    "needs_user": True,
                    "reason": (
                        f"faza inițială: sunt {n_hist} plasări confirmate în istoric; "
                        f"minim {settings.min_auto} pentru clasificare automată."
                    ),
                }
            )
    else:
        try:
            llm_rows = _llm_decisions(
                openai_client,  # type: ignore[arg-type]
                openai_model,
                folder_options=folder_options,
                placement_summaries=placement_summaries,
                file_rows=rows,
            )
        except Exception as e:  # noqa: BLE001
            for r in rows:
                sug = _simple_suggest(r["file_name"], r["preview"], folder_options)
                decisions_out.append(
                    {
                        "file_id": r["file_id"],
                        "file_name": r["file_name"],
                        "suggested_target_folder_id": sug,
                        "needs_user": True,
                        "reason": f"LLM indisponibil: {e}",
                    }
                )
        else:
            by_id = {str(x.get("file_id")): x for x in llm_rows if x.get("file_id")}
            for r in rows:
                fid = r["file_id"]
                hit = by_id.get(fid) or {}
                tid = str(hit.get("target_folder_id") or "")
                if tid not in valid_ids:
                    tid = _simple_suggest(r["file_name"], r["preview"], folder_options)
                    decisions_out.append(
                        {
                            "file_id": fid,
                            "file_name": r["file_name"],
                            "suggested_target_folder_id": tid,
                            "needs_user": True,
                            "reason": "Răspuns LLM lipsă / folder invalid; sugestie simplificată.",
                        }
                    )
                    continue
                decisions_out.append(
                    {
                        "file_id": fid,
                        "file_name": r["file_name"],
                        "suggested_target_folder_id": tid,
                        "needs_user": bool(hit.get("needs_user", False)),
                        "reason": str(hit.get("reason") or ""),
                    }
                )

    if settings.theme_paths_enabled and decisions_out:
        seen_folder_ids = {o["id"] for o in folder_options}
        for d in decisions_out:
            row = next((x for x in rows if x["file_id"] == d["file_id"]), None)
            if not row:
                continue
            label, segs = extension_destination_segments(row["file_name"])
            try:
                leaf_id, created_names = drive_google.ensure_folder_path_under_root(
                    service,
                    library_root_folder_id=settings.library_root_folder_id,
                    segments=segs,
                )
            except Exception as e:  # noqa: BLE001
                d["theme_path_error"] = str(e)
                d["theme_label"] = label
                d["path_rule"] = "extension"
                d["suggested_library_subpath"] = "/".join(segs)
                continue
            d["theme_label"] = label
            d["path_rule"] = "extension"
            d["suggested_library_subpath"] = "/".join(segs)
            d["folders_created_for_path"] = created_names
            d["suggested_target_folder_id"] = leaf_id
            extra_reason = (
                f"După extensie ({Path(row['file_name']).suffix or '(fără)'}): {label}. "
                f"Cale în bibliotecă: {d['suggested_library_subpath']}."
            )
            if created_names:
                extra_reason += f" Foldere noi create: {' → '.join(created_names)}."
            prev = (d.get("reason") or "").strip()
            d["reason"] = (prev + " " + extra_reason).strip() if prev else extra_reason
            if leaf_id not in seen_folder_ids:
                folder_options.append({"id": leaf_id, "name": d["suggested_library_subpath"]})
                seen_folder_ids.add(leaf_id)

    return {
        "ok": True,
        "phase": "auto" if auto_phase else "bootstrap",
        "library_placements_total": n_hist,
        "min_auto": settings.min_auto,
        "theme_paths_enabled": settings.theme_paths_enabled,
        "folder_options": folder_options,
        "files_in_stage_pending": [{"file_id": x["file_id"], "file_name": x["file_name"]} for x in rows],
        "previews": {x["file_id"]: x["preview"][:6000] for x in rows},
        "decisions": decisions_out,
    }


def _folder_name(service, folder_id: str, cache: dict[str, str]) -> str:
    if folder_id in cache:
        return cache[folder_id]
    try:
        meta = (
            service.files()
            .get(fileId=folder_id, fields="name", supportsAllDrives=True)
            .execute()
        )
        cache[folder_id] = str(meta.get("name") or folder_id)
    except Exception:  # noqa: BLE001
        cache[folder_id] = folder_id
    return cache[folder_id]


def copy_items(
    service,
    settings: DriveSettings,
    items: list[dict[str, str]],
) -> list[dict[str, Any]]:
    name_cache: dict[str, str] = {}
    results: list[dict[str, Any]] = []
    for it in items:
        source_id = (it.get("source_file_id") or it.get("file_id") or "").strip()
        target_id = (it.get("target_folder_id") or "").strip()
        if not source_id or not target_id:
            results.append({"ok": False, "source_file_id": source_id, "detail": "missing ids"})
            continue
        if drive_memory.already_copied(drive_memory.load_state(settings.memory_path), source_id):
            results.append({"ok": False, "source_file_id": source_id, "detail": "already copied"})
            continue
        try:
            meta = (
                service.files()
                .get(
                    fileId=source_id,
                    fields="id, name, mimeType",
                    supportsAllDrives=True,
                )
                .execute()
            )
            fname = str(meta.get("name") or "copy")
            mime = meta.get("mimeType")
        except Exception as e:  # noqa: BLE001
            results.append({"ok": False, "source_file_id": source_id, "detail": f"metadata: {e}"})
            continue
        preview = ""
        try:
            raw = drive_google.download_bytes(service, source_id, mime_type=mime, max_bytes=400_000)
            preview = _text_preview(raw, 3500)
        except Exception:  # noqa: BLE001
            preview = ""
        try:
            copied = drive_google.copy_file_to_folder(
                service,
                source_file_id=source_id,
                new_name=fname,
                target_folder_id=target_id,
            )
        except Exception as e:  # noqa: BLE001
            results.append({"ok": False, "source_file_id": source_id, "detail": str(e)})
            continue
        tgt_name = _folder_name(service, target_id, name_cache)
        drive_memory.record_copy(
            settings.memory_path,
            source_file_id=source_id,
            source_name=fname,
            preview=preview or "(fără preview)",
            target_folder_id=target_id,
            target_folder_name=tgt_name,
            copied_file_id=str(copied.get("id") or ""),
        )
        cid = str(copied.get("id") or "")
        results.append(
            {
                "ok": True,
                "source_file_id": source_id,
                "copied_file_id": copied.get("id"),
                "copied_web_link": drive_google.drive_file_web_link(cid) if cid else None,
                "target_folder_id": target_id,
                "target_folder_name": tgt_name,
                "name": fname,
            }
        )
    return results
