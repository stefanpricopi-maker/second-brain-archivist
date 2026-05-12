from __future__ import annotations

import io
import mimetypes
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

SCOPES = ["https://www.googleapis.com/auth/drive"]


def load_credentials(*, client_secret_path: Path, token_path: Path) -> Credentials:
    if not client_secret_path.is_file():
        raise FileNotFoundError(f"Missing OAuth client secret file: {client_secret_path}")
    if not token_path.is_file():
        raise FileNotFoundError(
            f"Missing OAuth token: {token_path}. Run: python scripts/drive_auth.py"
        )
    creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if creds.valid:
        return creds
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_path.write_text(creds.to_json(), encoding="utf-8")
        return creds
    raise RuntimeError("Token invalid/expired; run python scripts/drive_auth.py again.")


def drive_service(creds: Credentials):
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def list_nonfolder_children(service, folder_id: str, *, page_size: int = 100) -> list[dict[str, Any]]:
    q = (
        f"'{folder_id}' in parents and trashed = false and "
        "mimeType != 'application/vnd.google-apps.folder'"
    )
    items: list[dict[str, Any]] = []
    token: str | None = None
    while True:
        resp = (
            service.files()
            .list(
                q=q,
                spaces="drive",
                fields="nextPageToken, files(id, name, mimeType, modifiedTime, size)",
                pageSize=page_size,
                pageToken=token,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )
        items.extend(resp.get("files") or [])
        token = resp.get("nextPageToken")
        if not token:
            break
    return items


def sanitize_drive_folder_name(name: str) -> str:
    """Nume sigur pentru folder nou în Drive."""
    s = (name or "").strip()
    for ch in ("/", "\\", "\x00", "\n", "\r"):
        s = s.replace(ch, "-")
    s = s.strip() or "Folder"
    return s[:200]


def find_child_folder_id(service, parent_id: str, folder_name: str) -> str | None:
    """Găsește un subfolder direct după nume (fără sensibilitate la majuscule)."""
    want = sanitize_drive_folder_name(folder_name).lower()
    if not want:
        return None
    for f in list_subfolders(service, parent_id):
        n = str(f.get("name") or "").strip().lower()
        if n == want:
            fid = f.get("id")
            if fid:
                return str(fid)
    return None


def create_child_folder(service, *, parent_id: str, name: str) -> dict[str, Any]:
    clean = sanitize_drive_folder_name(name)
    body: dict[str, Any] = {
        "name": clean,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id],
    }
    return service.files().create(body=body, fields="id,name", supportsAllDrives=True).execute()


def ensure_folder_path_under_root(
    service,
    *,
    library_root_folder_id: str,
    segments: list[str],
) -> tuple[str, list[str]]:
    """
    Creează ierarhia `segments` sub `library_root_folder_id` dacă lipsește.

    Returnează (folder_id_frunză, nume_segmente_abia_create).
    """
    parent = library_root_folder_id
    created: list[str] = []
    for raw in segments:
        seg = sanitize_drive_folder_name(raw)
        if not seg:
            continue
        hit = find_child_folder_id(service, parent, seg)
        if hit:
            parent = hit
            continue
        out = create_child_folder(service, parent_id=parent, name=seg)
        created.append(str(out.get("name") or seg))
        parent = str(out["id"])
    return parent, created


def list_subfolders(service, parent_id: str) -> list[dict[str, Any]]:
    q = (
        f"'{parent_id}' in parents and trashed = false and "
        "mimeType = 'application/vnd.google-apps.folder'"
    )
    resp = (
        service.files()
        .list(
            q=q,
            spaces="drive",
            fields="files(id, name)",
            pageSize=100,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        )
        .execute()
    )
    return list(resp.get("files") or [])


def download_bytes(service, file_id: str, *, mime_type: str | None, max_bytes: int = 12_000_000) -> bytes:
    try:
        if mime_type and mime_type.startswith("application/vnd.google-apps."):
            export_mime = "text/plain"
            if mime_type == "application/vnd.google-apps.spreadsheet":
                export_mime = "text/csv"
            request = service.files().export_media(fileId=file_id, mimeType=export_mime)
        else:
            request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request, chunksize=1024 * 1024)
        done = False
        while not done:
            status, done = downloader.next_chunk()
            if fh.tell() > max_bytes:
                break
        return fh.getvalue()[:max_bytes]
    except HttpError as e:
        raise RuntimeError(f"Drive download failed: {e}") from e


def upload_file_to_folder(
    service,
    *,
    folder_id: str,
    filename: str,
    content: bytes,
    mime_type: str | None = None,
) -> dict[str, Any]:
    """
    Încarcă un fișier binar într-un folder Drive (ex. Stage).
    Fișiere mari folosesc upload resumable (peste 5 MiB).
    """
    name = (filename or "upload").strip() or "upload"
    mt = mime_type or mimetypes.guess_type(name)[0] or "application/octet-stream"
    body: dict[str, Any] = {"name": name, "parents": [folder_id]}
    stream = io.BytesIO(content)
    size = len(content)
    resumable = size > 5 * 1024 * 1024
    media = MediaIoBaseUpload(stream, mimetype=mt, resumable=resumable, chunksize=256 * 1024)
    try:
        req = service.files().create(
            body=body,
            media_body=media,
            fields="id, name, mimeType, webViewLink, webContentLink",
            supportsAllDrives=True,
        )
        if not resumable:
            return req.execute()
        response = None
        while response is None:
            _status, response = req.next_chunk()
        return response
    except HttpError as e:
        raise RuntimeError(f"Drive upload failed: {e}") from e


def drive_file_web_link(file_id: str) -> str:
    return f"https://drive.google.com/file/{file_id}/view"


def copy_file_to_folder(
    service,
    *,
    source_file_id: str,
    new_name: str,
    target_folder_id: str,
) -> dict[str, Any]:
    body: dict[str, Any] = {"name": new_name, "parents": [target_folder_id]}
    return (
        service.files()
        .copy(
            fileId=source_file_id,
            body=body,
            supportsAllDrives=True,
            fields="id, name, parents",
        )
        .execute()
    )
