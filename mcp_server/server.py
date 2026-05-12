"""
Second Brain — MCP server (căutare bibliotecă + arhivare Markdown).

Rulează din rădăcina proiectului:

    python -m mcp_server.server

Cursor: adaugă server MCP cu comandă de mai sus și cwd la acest folder.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env")

from app import drive_google  # noqa: E402
from app.connectors import BrowserDownloadSink, ObsidianVaultSink  # noqa: E402
from app.connectors.notion_api import load_notion_sink_from_env  # noqa: E402
from app.drive_ingest import copy_drive_items_with_optional_rag  # noqa: E402
from app.drive_organize import library_folder_options, propose_stage  # noqa: E402
from app.drive_settings import load_drive_settings  # noqa: E402
from app.drive_wizard import (  # noqa: E402
    auto_place_uploaded_file_ids,
    chunk_source_file_ids,
    merge_wizard_auto_place_payloads,
)
from app.rag import LibraryRAGIndex  # noqa: E402
from openai import OpenAI  # noqa: E402

mcp = FastMCP("second-brain-archivist")

_rag = LibraryRAGIndex(
    persist_dir=Path(os.getenv("VECTORSTORE_DIR", "./data/vectorstore")).resolve(),
)


def _openai_client() -> OpenAI | None:
    key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not key:
        return None
    return OpenAI(api_key=key)


def _sink() -> Any:
    raw = (os.getenv("OBSIDIAN_VAULT_PATH") or "").strip()
    if raw:
        sub = os.getenv("OBSIDIAN_DEFAULT_SUBDIR", "SecondBrain/Inbox").strip()
        return ObsidianVaultSink(Path(raw), default_subdir=sub)
    notion = load_notion_sink_from_env()
    if notion is not None:
        return notion
    exports = Path(os.getenv("EXPORTS_DIR", "./data/exports")).resolve()
    return BrowserDownloadSink(exports)


@mcp.tool()
def library_search(query: str, k: int = 8) -> str:
    """Caută în indexul RAG (cărți + notițe ingest). Returnează JSON cu fragmente și metadata."""
    q = (query or "").strip()
    if not q:
        return json.dumps({"ok": False, "error": "empty query"}, ensure_ascii=False)
    k = max(1, min(24, int(k)))
    chunks = _rag.query(q, k=k)
    return json.dumps({"ok": True, "count": len(chunks), "results": chunks}, ensure_ascii=False)


@mcp.tool()
def library_chunk_count() -> str:
    """Număr de fragmente în colecția Chroma (după ingest)."""
    return json.dumps({"ok": True, "chunks": _rag.count()}, ensure_ascii=False)


@mcp.tool()
def archive_save_markdown_page(title: str, body_markdown: str, subdirectory: str | None = None) -> str:
    """
    Salvează o pagină Markdown: Obsidian (dacă OBSIDIAN_VAULT_PATH), Notion (dacă NOTION_TOKEN + parent),
    altfel link descărcabil (Chrome).
    """
    sink = _sink()
    res = sink.save_markdown_page(
        title=title.strip(),
        body_markdown=body_markdown,
        subdirectory=subdirectory,
    )
    return json.dumps(
        {
            "ok": res.ok,
            "destination": res.destination,
            "path_or_url": res.path_or_url,
            "detail": res.detail,
        },
        ensure_ascii=False,
    )


@mcp.tool()
def notion_create_page(title: str, body_markdown: str, subdirectory: str | None = None) -> str:
    """
    Creează o pagină în Notion (NOTION_TOKEN + NOTION_PARENT_PAGE_ID sau NOTION_DATABASE_ID).
    Ignoră Obsidian: folosește doar integrarea Notion.
    """
    sink = load_notion_sink_from_env()
    if sink is None:
        return json.dumps(
            {
                "ok": False,
                "error": "notion_not_configured",
                "detail": "Setează NOTION_TOKEN și exact unul dintre NOTION_PARENT_PAGE_ID / NOTION_DATABASE_ID.",
            },
            ensure_ascii=False,
        )
    res = sink.save_markdown_page(
        title=title.strip(),
        body_markdown=body_markdown,
        subdirectory=subdirectory,
    )
    return json.dumps(
        {
            "ok": res.ok,
            "destination": res.destination,
            "path_or_url": res.path_or_url,
            "detail": res.detail,
        },
        ensure_ascii=False,
    )


def _drive_service():
    st = load_drive_settings(PROJECT_ROOT)
    if not st:
        return None, None
    try:
        creds = drive_google.load_credentials(
            client_secret_path=st.client_secret_path,
            token_path=st.token_path,
        )
    except (FileNotFoundError, RuntimeError):
        return st, None
    return st, drive_google.drive_service(creds)


@mcp.tool()
def drive_status() -> str:
    """Stare Google Drive (config + token) pentru Stage → bibliotecă."""
    st = load_drive_settings(PROJECT_ROOT)
    if not st:
        return json.dumps({"enabled": False}, ensure_ascii=False)
    return json.dumps(
        {
            "enabled": True,
            "stage_folder_id": st.stage_folder_id,
            "library_root_folder_id": st.library_root_folder_id,
            "client_secret_present": st.client_secret_path.is_file(),
            "token_present": st.token_path.is_file(),
            "memory_path": str(st.memory_path),
            "min_auto": st.min_auto,
        },
        ensure_ascii=False,
    )


@mcp.tool()
def drive_library_folders() -> str:
    """Listează folderele țintă sub rădăcina bibliotecii (Drive API)."""
    st, svc = _drive_service()
    if not st or svc is None:
        return json.dumps({"ok": False, "error": "drive_not_ready"}, ensure_ascii=False)
    opts = library_folder_options(svc, st.library_root_folder_id)
    return json.dumps({"ok": True, "folder_options": opts}, ensure_ascii=False)


@mcp.tool()
def drive_propose_stage() -> str:
    """Scanează folderul Stage, previzualizează fișiere noi, propune foldere (bootstrap sau LLM)."""
    st, svc = _drive_service()
    if not st or svc is None:
        return json.dumps({"ok": False, "error": "drive_not_ready"}, ensure_ascii=False)
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    out = propose_stage(svc, st, openai_client=_openai_client(), openai_model=model)
    return json.dumps(out, ensure_ascii=False)


@mcp.tool()
def drive_copy_items(items_json: str) -> str:
    """
    Copiază din Stage în bibliotecă. `items_json` poate fi:
    - listă: [{"source_file_id":"...","target_folder_id":"..."}, ...]
    - obiect: {"items":[...], "ingest_to_rag": true} — după copiere, indexare în RAG local.
    """
    st, svc = _drive_service()
    if not st or svc is None:
        return json.dumps({"ok": False, "error": "drive_not_ready"}, ensure_ascii=False)
    try:
        raw = json.loads(items_json or "[]")
    except json.JSONDecodeError as e:
        return json.dumps({"ok": False, "error": f"invalid json: {e}"}, ensure_ascii=False)
    if isinstance(raw, list):
        items = raw
        ingest_to_rag = False
    elif isinstance(raw, dict):
        items = raw.get("items") or []
        ingest_to_rag = bool(raw.get("ingest_to_rag"))
        if not isinstance(items, list):
            return json.dumps({"ok": False, "error": "items must be a list"}, ensure_ascii=False)
    else:
        return json.dumps({"ok": False, "error": "payload must be list or object"}, ensure_ascii=False)
    out = copy_drive_items_with_optional_rag(
        svc,
        st,
        [dict(x) for x in items],
        rag=_rag,
        ingest_to_rag=ingest_to_rag,
    )
    return json.dumps(out, ensure_ascii=False)


@mcp.tool()
def drive_wizard_auto_place(source_file_ids_json: str, ingest_to_rag: bool = False) -> str:
    """
    Plasare automată wizard (aceeași logică ca `POST /drive/wizard/auto-place`): primește un JSON array
    de Google `file_id` din Stage. Listele lungi sunt împărțite automat în bucăți (max 120/cerere) și rezultatele unite.
    Răspuns: JSON cu `succeeded`, `needs_manual`, `skipped`, `folder_options`, `rag_chunks`, `ok`.
    """
    st, svc = _drive_service()
    if not st or svc is None:
        return json.dumps({"ok": False, "error": "drive_not_ready"}, ensure_ascii=False)
    try:
        raw = json.loads(source_file_ids_json or "[]")
    except json.JSONDecodeError as e:
        return json.dumps({"ok": False, "error": f"invalid json: {e}"}, ensure_ascii=False)
    if not isinstance(raw, list):
        return json.dumps({"ok": False, "error": "payload must be a JSON array of file ids"}, ensure_ascii=False)
    ids = [str(x).strip() for x in raw if str(x).strip()]
    if not ids:
        return json.dumps({"ok": False, "error": "empty source_file_ids"}, ensure_ascii=False)
    parts: list[dict[str, Any]] = []
    for chunk in chunk_source_file_ids(ids):
        out = auto_place_uploaded_file_ids(
            svc,
            st,
            source_file_ids=chunk,
            ingest_to_rag=ingest_to_rag,
            rag=_rag,
        )
        parts.append(out)
    merged = merge_wizard_auto_place_payloads(parts)
    return json.dumps(merged, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run()
