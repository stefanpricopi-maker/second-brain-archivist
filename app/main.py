from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.connectors import BrowserDownloadSink, ObsidianVaultSink, StubArchiveSink
from app.ingest import (
    docs_to_chunks,
    extract_docx,
    extract_pdf,
    extract_text_like,
    save_upload,
)
from app import drive_google
from app.drive_ingest import copy_drive_items_with_optional_rag
from app.drive_organize import library_folder_options, propose_stage
from app.drive_settings import load_drive_settings
from app.drive_util import folder_id_from_drive_url
from app.rag import LibraryRAGIndex
from openai import OpenAI

load_dotenv()

LIBRARY_DIR = Path(os.getenv("LIBRARY_DIR", "./data/library")).resolve()
UPLOADS_DIR = Path(os.getenv("UPLOADS_DIR", "./data/uploads")).resolve()
VECTORSTORE_DIR = Path(os.getenv("VECTORSTORE_DIR", "./data/vectorstore")).resolve()
EXPORTS_DIR = Path(os.getenv("EXPORTS_DIR", "./data/exports")).resolve()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
_has_openai_key = bool((os.getenv("OPENAI_API_KEY") or "").strip())
LLM_MODE = (os.getenv("LLM_MODE") or ("openai" if _has_openai_key else "disabled")).strip().lower()
if LLM_MODE == "openai" and not _has_openai_key:
    LLM_MODE = "disabled"
OBSIDIAN_VAULT = (os.getenv("OBSIDIAN_VAULT_PATH") or "").strip()
OBSIDIAN_SUBDIR = os.getenv("OBSIDIAN_DEFAULT_SUBDIR", "SecondBrain/Inbox").strip()

rag = LibraryRAGIndex(persist_dir=VECTORSTORE_DIR)
client = (
    OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    if LLM_MODE == "openai" and _has_openai_key
    else None
)


def _archive_sink() -> Any:
    if OBSIDIAN_VAULT:
        return ObsidianVaultSink(Path(OBSIDIAN_VAULT), default_subdir=OBSIDIAN_SUBDIR)
    # Default: compatibil cu Chrome (download link). Stub rămâne pentru demo strict „fără disc”.
    return BrowserDownloadSink(EXPORTS_DIR)


app = FastAPI(
    title="Second Brain / Arhivist",
    version="0.1.0",
    openapi_tags=[
        {"name": "meta", "description": "Health și stare index."},
        {"name": "library", "description": "Căutare RAG în bibliotecă."},
        {"name": "chat", "description": "Întrebări cu context din cărți și notițe."},
        {"name": "archive", "description": "Salvare sinteză ca fișier descărcabil (Chrome) sau Obsidian (opțional)."},
        {"name": "drive", "description": "Google Drive: Stage → bibliotecă (copiere, clasificare)."},
    ],
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DRIVE_SETTINGS = load_drive_settings(PROJECT_ROOT)
STATIC_DIR = PROJECT_ROOT / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        rid = (request.headers.get("x-request-id") or "").strip() or str(uuid.uuid4())
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response


app.add_middleware(RequestIdMiddleware)


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok", "service": "second-brain-archivist"}


@app.get("/status", tags=["meta"])
def status() -> dict[str, Any]:
    return {
        "library_dir": str(LIBRARY_DIR),
        "library_dir_exists": LIBRARY_DIR.exists(),
        "uploads_dir": str(UPLOADS_DIR),
        "vectorstore_dir": str(VECTORSTORE_DIR),
        "rag_chunks": rag.count(),
        "llm_mode": LLM_MODE,
        "archive": {
            "mode": "obsidian" if OBSIDIAN_VAULT else "download",
            "vault_set": bool(OBSIDIAN_VAULT),
            "exports_dir": str(EXPORTS_DIR),
        },
        "drive": {
            "enabled": bool(DRIVE_SETTINGS),
            "token_present": bool(DRIVE_SETTINGS and DRIVE_SETTINGS.token_path.is_file()),
        },
    }


@app.get("/search", tags=["library"])
def search(q: str, k: int = 8) -> dict[str, Any]:
    q = (q or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="Missing q.")
    if k < 1 or k > 24:
        raise HTTPException(status_code=400, detail="k must be 1..24")
    chunks = rag.query(q, k=k)
    return {"query": q, "k": k, "results": chunks}


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=20_000)
    k: int = Field(default=8, ge=1, le=24)


class ChatResponse(BaseModel):
    answer: str
    used_chunks: list[dict[str, Any]]

class IngestResponse(BaseModel):
    status: str
    files: list[dict[str, Any]]
    added_chunks: int
    rag_chunks: int


def _fallback_answer(query: str, chunks: list[dict[str, Any]]) -> str:
    if not chunks:
        return (
            "Nu am găsit fragmente în index (rulează `python scripts/ingest_library.py` după ce pui PDF/MD în "
            f"{LIBRARY_DIR}). Întrebarea ta: {query[:200]}"
        )
    parts = [
        "Iată ce am găsit în bibliotecă (fragmente; verifică sursa în metadata):\n",
    ]
    for i, ch in enumerate(chunks, start=1):
        md = ch.get("metadata") or {}
        src = md.get("source", "?")
        page = md.get("page")
        head = f"[{i}] {src}" + (f" p.{page}" if page is not None else "")
        parts.append(f"\n### {head}\n{ch.get('text', '')[:1200]}")
    parts.append(
        "\n\n_(Mod LLM dezactivat: răspunsul e doar citate/scurte extrase. "
        "Pune `LLM_MODE=openai` pentru sinteză liberă.)_"
    )
    return "\n".join(parts)


@app.post("/chat", response_model=ChatResponse, tags=["chat"])
def chat(req: ChatRequest) -> ChatResponse:
    query = req.message.strip()
    chunks = rag.query(query, k=req.k)
    if LLM_MODE != "openai" or client is None:
        return ChatResponse(answer=_fallback_answer(query, chunks), used_chunks=chunks)

    rendered = []
    for i, ch in enumerate(chunks, start=1):
        md = ch.get("metadata") or {}
        src = md.get("source", "?")
        header = f"[{i}] {src}"
        rendered.append(header + "\n" + (ch.get("text") or ""))
    user_block = query + "\n\nFragmente:\n" + "\n---\n".join(rendered) if rendered else query

    try:
        r = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Ești arhivistul unei biblioteci personale. Răspunde concis în limba utilizatorului; "
                        "citează sursa (fișier / pagină) când te bazezi pe un fragment. "
                        "Nu inventa citate care nu apar în fragmente."
                    ),
                },
                {"role": "user", "content": user_block},
            ],
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM error: {e}") from e

    answer = (r.choices[0].message.content or "").strip()
    if not answer:
        raise HTTPException(status_code=502, detail="Empty LLM response")
    return ChatResponse(answer=answer, used_chunks=chunks)

@app.post("/ingest/files", response_model=IngestResponse, tags=["library"])
async def ingest_files(files: list[UploadFile] = File(...)) -> IngestResponse:
    summaries: list[dict[str, Any]] = []
    added = 0
    for f in files:
        name = (f.filename or "upload").strip()
        raw = await f.read()
        if not raw:
            summaries.append({"filename": name, "status": "error", "detail": "empty"})
            continue

        saved = save_upload(uploads_dir=UPLOADS_DIR, filename=name, content=raw)
        ext = saved.suffix.lower()
        try:
            if ext == ".pdf":
                doc = extract_pdf(filename=name, content=raw)
            elif ext in (".md", ".txt"):
                doc = extract_text_like(filename=name, content=raw, source_type=ext.lstrip("."))
            elif ext == ".docx":
                doc = extract_docx(filename=name, content=raw)
            elif ext == ".doc":
                summaries.append(
                    {
                        "filename": name,
                        "status": "error",
                        "detail": "format .doc (legacy) nu e suportat încă; convertește la .docx sau PDF.",
                    }
                )
                continue
            else:
                summaries.append(
                    {
                        "filename": name,
                        "status": "error",
                        "detail": f"unsupported file type: {ext or '(no ext)'}",
                    }
                )
                continue

            texts, metas, ids = docs_to_chunks(doc=doc)
            if not texts:
                summaries.append(
                    {
                        "filename": name,
                        "status": "error",
                        "detail": "nu s-a extras text (PDF scanat? OCR încă neimplementat).",
                        "saved_path": str(saved),
                    }
                )
                continue

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
                }
            )
        except Exception as e:
            summaries.append({"filename": name, "status": "error", "detail": str(e), "saved_path": str(saved)})

    return IngestResponse(
        status="ok",
        files=summaries,
        added_chunks=added,
        rag_chunks=rag.count(),
    )


class ArchivePageRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    body_markdown: str = Field(..., min_length=1, max_length=200_000)
    subdirectory: str | None = Field(default=None, max_length=500)


@app.post("/archive/page", tags=["archive"])
def archive_page(req: ArchivePageRequest) -> dict[str, Any]:
    sink = _archive_sink()
    res = sink.save_markdown_page(
        title=req.title.strip(),
        body_markdown=req.body_markdown,
        subdirectory=req.subdirectory,
    )
    return {"ok": res.ok, "destination": res.destination, "path_or_url": res.path_or_url, "detail": res.detail}


@app.get("/archive/files/{rel_path:path}", tags=["archive"])
def archive_download(rel_path: str) -> FileResponse:
    # Strict: nu permitem ieșire din EXPORTS_DIR.
    base = EXPORTS_DIR.resolve()
    target = (base / rel_path).resolve()
    if base not in target.parents and target != base:
        raise HTTPException(status_code=400, detail="Invalid path.")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Not found.")
    return FileResponse(str(target), filename=target.name)


def _drive_service_or_503() -> tuple[Any, Any]:
    if not DRIVE_SETTINGS:
        raise HTTPException(
            status_code=503,
            detail="Drive nu e configurat (GOOGLE_DRIVE_STAGE_FOLDER_ID, GOOGLE_DRIVE_LIBRARY_ROOT_FOLDER_ID).",
        )
    try:
        creds = drive_google.load_credentials(
            client_secret_path=DRIVE_SETTINGS.client_secret_path,
            token_path=DRIVE_SETTINGS.token_path,
        )
    except (FileNotFoundError, RuntimeError) as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    return DRIVE_SETTINGS, drive_google.drive_service(creds)


@app.get("/drive/status", tags=["drive"])
def drive_status() -> dict[str, Any]:
    if not DRIVE_SETTINGS:
        return {
            "enabled": False,
            "detail": "Setează GOOGLE_DRIVE_STAGE_FOLDER_ID și GOOGLE_DRIVE_LIBRARY_ROOT_FOLDER_ID.",
        }
    st = DRIVE_SETTINGS
    return {
        "enabled": True,
        "stage_folder_id": st.stage_folder_id,
        "library_root_folder_id": st.library_root_folder_id,
        "client_secret_present": st.client_secret_path.is_file(),
        "token_present": st.token_path.is_file(),
        "memory_path": str(st.memory_path),
        "min_auto": st.min_auto,
    }


@app.get("/drive/folders", tags=["drive"])
def drive_folders() -> dict[str, Any]:
    settings, svc = _drive_service_or_503()
    opts = library_folder_options(svc, settings.library_root_folder_id)
    return {"ok": True, "folder_options": opts}


@app.post("/drive/propose", tags=["drive"])
def drive_propose() -> dict[str, Any]:
    settings, svc = _drive_service_or_503()
    return propose_stage(
        svc,
        settings,
        openai_client=client,
        openai_model=OPENAI_MODEL,
    )


class DriveCopyItem(BaseModel):
    source_file_id: str = Field(..., min_length=1, max_length=256)
    target_folder_id: str = Field(..., min_length=1, max_length=256)


class DriveCopyRequest(BaseModel):
    items: list[DriveCopyItem] = Field(..., min_length=1, max_length=40)
    ingest_to_rag: bool = Field(
        default=False,
        description="După copiere, descarcă fișierul din bibliotecă și îl adaugă în indexul Chroma.",
    )


@app.post("/drive/copy", tags=["drive"])
def drive_copy(req: DriveCopyRequest) -> dict[str, Any]:
    settings, svc = _drive_service_or_503()
    payload = [i.model_dump() for i in req.items]
    return copy_drive_items_with_optional_rag(
        svc,
        settings,
        payload,
        rag=rag,
        ingest_to_rag=req.ingest_to_rag,
    )


@app.get("/drive/folder-id", tags=["drive"])
def drive_folder_id(url: str) -> dict[str, str]:
    fid = folder_id_from_drive_url(url)
    if not fid:
        raise HTTPException(status_code=400, detail="Nu pot extrage folder ID din URL.")
    return {"folder_id": fid}


@app.get("/", tags=["meta"])
def root() -> dict[str, str]:
    # JSON root rămâne util pentru API users, dar UI se servește la /static/.
    return {
        "service": "second-brain-archivist",
        "docs": "/docs",
        "ui": "/static/index.html",
        "hint": "POST /ingest/files, POST /chat, GET /search, POST /archive/page, GET /drive/status — vezi README.",
    }
