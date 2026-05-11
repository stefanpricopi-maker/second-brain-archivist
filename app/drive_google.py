from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

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
