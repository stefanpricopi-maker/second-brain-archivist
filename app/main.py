from __future__ import annotations

import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.connectors import BrowserDownloadSink, ObsidianVaultSink
from app.connectors.notion_api import load_notion_sink_from_env
from app.ingest import (
    docs_to_chunks,
    extract_docx,
    extract_epub,
    extract_pdf,
    extract_pdf_for_voice_shelf,
    extract_text_like,
    save_upload,
)
from app import drive_google
from app.drive_batch import batch_auto_organize_from_folder
from app.drive_ingest import copy_drive_items_with_optional_rag
from app.drive_wizard import WIZARD_AUTO_PLACE_MAX_IDS, auto_place_uploaded_file_ids
from app.drive_organize import library_folder_options, propose_stage
from app.drive_settings import load_drive_settings
from app.drive_util import folder_id_from_drive_url
from app.logging_setup import configure_logging, request_id_ctx
from app.middleware.http_limits import RateLimitMiddleware, StaticCacheControlMiddleware
from app.ocr_pdf import ocr_backend_status
from app.rag import LibraryRAGIndex
from openai import OpenAI

load_dotenv()
configure_logging()

log = logging.getLogger(__name__)

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
    # Local (Obsidian) are prioritate față de Notion dacă ambele sunt setate.
    if OBSIDIAN_VAULT:
        return ObsidianVaultSink(Path(OBSIDIAN_VAULT), default_subdir=OBSIDIAN_SUBDIR)
    notion = load_notion_sink_from_env()
    if notion is not None:
        return notion
    return BrowserDownloadSink(EXPORTS_DIR)


app = FastAPI(
    title="Second Brain / Arhivist",
    version="0.1.0",
    openapi_tags=[
        {"name": "meta", "description": "Health și stare index."},
        {"name": "library", "description": "Căutare RAG în bibliotecă."},
        {"name": "chat", "description": "Întrebări cu context din cărți și notițe."},
        {"name": "archive", "description": "Salvare sinteză: Obsidian, Notion (token + parent), sau download Chrome."},
        {"name": "drive", "description": "Google Drive: Stage → bibliotecă (copiere, clasificare)."},
        {
            "name": "voice_library",
            "description": "Cărți scanate (OCR) și întrebări restrânse la o sursă din bibliotecă; separat de Drive.",
        },
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
        request.state.request_id = rid
        token = request_id_ctx.set(rid)
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = rid
            return response
        finally:
            request_id_ctx.reset(token)


app.add_middleware(StaticCacheControlMiddleware, prefix="/static", max_age=3600)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(RequestIdMiddleware)


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok", "service": "second-brain-archivist"}


@app.get("/status", tags=["meta"])
def status() -> dict[str, Any]:
    notion_sink = load_notion_sink_from_env()
    return {
        "library_dir": str(LIBRARY_DIR),
        "library_dir_exists": LIBRARY_DIR.exists(),
        "uploads_dir": str(UPLOADS_DIR),
        "vectorstore_dir": str(VECTORSTORE_DIR),
        "rag_chunks": rag.count(),
        "llm_mode": LLM_MODE,
        "archive": {
            "mode": (
                "obsidian"
                if OBSIDIAN_VAULT
                else ("notion" if notion_sink is not None else "download")
            ),
            "vault_set": bool(OBSIDIAN_VAULT),
            "notion_configured": notion_sink is not None,
            "exports_dir": str(EXPORTS_DIR),
        },
        "drive": {
            "enabled": bool(DRIVE_SETTINGS),
            "token_present": bool(DRIVE_SETTINGS and DRIVE_SETTINGS.token_path.is_file()),
        },
        "voice_library": {"ocr": ocr_backend_status()},
    }


def _metadata_source_filter(source: str | None) -> dict[str, Any] | None:
    """Filtru Chroma pe câmpul metadata `source` (egalitate exactă)."""
    s = (source or "").strip()
    if not s:
        return None
    if len(s) > 512:
        raise HTTPException(status_code=422, detail="Parametrul «source» e prea lung (max 512).")
    return {"source": {"$eq": s}}


@app.get("/search", tags=["library"])
def search(q: str, k: int = 8, source: str | None = None) -> dict[str, Any]:
    q = (q or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="Missing q.")
    if k < 1 or k > 24:
        raise HTTPException(status_code=400, detail="k must be 1..24")
    where = _metadata_source_filter(source)
    chunks = rag.query(q, k=k, where=where)
    return {"query": q, "k": k, "source": (source or "").strip() or None, "results": chunks}


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=20_000)
    k: int = Field(default=8, ge=1, le=24)
    source: str | None = Field(
        default=None,
        max_length=512,
        description="Opțional: restrânge fragmentele RAG la metadata «source» (aceeași valoare ca în listă / upload).",
    )


class ChatResponse(BaseModel):
    answer: str
    used_chunks: list[dict[str, Any]]

class IngestResponse(BaseModel):
    status: str
    files: list[dict[str, Any]]
    added_chunks: int
    rag_chunks: int


def _fallback_answer(query: str, chunks: list[dict[str, Any]], *, source: str | None = None) -> str:
    if not chunks:
        src = (source or "").strip()
        if src:
            return (
                f"Nu am găsit fragmente în index pentru sursa «{src}» și întrebarea ta. "
                "Verifică că ai selectat exact sursa din listă sau re-indexează cartea din tab-ul «Cărți & voce». "
                f"Întrebare: {query[:200]}"
            )
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
    where = _metadata_source_filter(req.source)
    chunks = rag.query(query, k=req.k, where=where)
    if LLM_MODE != "openai" or client is None:
        return ChatResponse(
            answer=_fallback_answer(query, chunks, source=req.source),
            used_chunks=chunks,
        )

    rendered = []
    for i, ch in enumerate(chunks, start=1):
        md = ch.get("metadata") or {}
        src = md.get("source", "?")
        header = f"[{i}] {src}"
        rendered.append(header + "\n" + (ch.get("text") or ""))
    sf = (req.source or "").strip()
    prefix = (
        f"Contextul este restrâns la o singură sursă din bibliotecă (metadata source = «{sf}»).\n\n"
        if sf
        else ""
    )
    user_block = prefix + (query + "\n\nFragmente:\n" + "\n---\n".join(rendered) if rendered else query)

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
                        "detail": "nu s-a extras text util. Pentru scanări folosește tab-ul «Cărți & voce» (OCR) sau `POST /voice-library/ingest`.",
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


@app.get(
    "/voice-library/ocr-status",
    tags=["voice_library"],
    summary="Stare OCR (Tesseract + poppler)",
    description="Verifică dacă serverul poate rula OCR pentru PDF-uri scanate (dependențe Python + binar tesseract).",
)
def voice_library_ocr_status() -> dict[str, Any]:
    return ocr_backend_status()


@app.get(
    "/voice-library/sources",
    tags=["voice_library"],
    summary="Surse distincte în index",
    description="Listează valorile `source` din metadata Chroma (pentru a restrânge chat-ul la o carte).",
)
def voice_library_sources() -> dict[str, Any]:
    return {"ok": True, "sources": rag.list_sources(), "rag_chunks": rag.count()}


@app.post(
    "/voice-library/ingest",
    response_model=IngestResponse,
    tags=["voice_library"],
    summary="Încarcă PDF scanat (cu OCR dacă e nevoie)",
    description=(
        "Multipart: `files` (PDF). Form: `book_label` (opțional, afișat în listă), `force_ocr` = auto|true|false. "
        "Zona e separată de Google Drive; fișierele merg în uploads local + index RAG."
    ),
)
async def voice_library_ingest(
    files: list[UploadFile] = File(...),
    book_label: str = Form(""),
    force_ocr: str = Form("auto"),
) -> IngestResponse:
    summaries: list[dict[str, Any]] = []
    added = 0
    bl = (book_label or "").strip() or None
    for f in files:
        name = (f.filename or "upload").strip() or "upload"
        raw = await f.read()
        if not raw:
            summaries.append({"filename": name, "status": "error", "detail": "empty"})
            continue
        if not name.lower().endswith(".pdf"):
            summaries.append(
                {
                    "filename": name,
                    "status": "error",
                    "detail": "În «Cărți & voce» acceptăm doar .pdf (scanat sau text).",
                }
            )
            continue

        saved = save_upload(uploads_dir=UPLOADS_DIR, filename=name, content=raw)
        try:
            doc = extract_pdf_for_voice_shelf(
                filename=name,
                content=raw,
                book_label=bl,
                force_ocr=(force_ocr or "auto").strip(),
            )
            texts, metas, ids = docs_to_chunks(doc=doc)
            if not texts:
                summaries.append(
                    {
                        "filename": name,
                        "status": "error",
                        "detail": "nu s-au putut genera fragmente după OCR/extragere.",
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
        except Exception as e:  # noqa: BLE001
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
    try:
        target = resolve_export_download(EXPORTS_DIR, rel_path)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path.") from None
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
    stage_url = (os.getenv("GOOGLE_DRIVE_STAGE_FOLDER_URL") or "").strip()
    client_ok = st.client_secret_path.is_file()
    token_ok = st.token_path.is_file()
    ready_for_api = client_ok and token_ok
    hints: list[str] = []
    if not client_ok:
        hints.append(f"Lipsește client secret OAuth: {st.client_secret_path}")
    if not token_ok:
        hints.append("Rulează din rădăcina proiectului: python scripts/drive_auth.py")
    return {
        "enabled": True,
        "ready_for_api": ready_for_api,
        "setup_hint": " — ".join(hints) if hints else None,
        "theme_paths_enabled": st.theme_paths_enabled,
        "stage_folder_id": st.stage_folder_id,
        "stage_folder_url": stage_url or None,
        "library_root_folder_id": st.library_root_folder_id,
        "client_secret_present": client_ok,
        "token_present": token_ok,
        "memory_path": str(st.memory_path),
        "min_auto": st.min_auto,
    }


@app.get("/drive/folders", tags=["drive"])
def drive_folders() -> dict[str, Any]:
    settings, svc = _drive_service_or_503()
    opts = library_folder_options(svc, settings.library_root_folder_id)
    return {"ok": True, "folder_options": opts}


MAX_DRIVE_STAGE_UPLOAD = 32 * 1024 * 1024


@app.post(
    "/drive/stage/upload",
    tags=["drive"],
    summary="Încarcă fișiere în folderul Stage",
    description=(
        "Multipart: câmpul `files` (repetat). Un fișier per parte sau mai multe în aceeași cerere. "
        "Maxim ~32 MiB per fișier. Răspuns: `files[]` cu `status`, `file_id`, linkuri."
    ),
)
async def drive_stage_upload(files: list[UploadFile] = File(...)) -> dict[str, Any]:
    """Încarcă unul sau mai multe fișiere în folderul Stage din Google Drive."""
    t0 = time.perf_counter()
    settings, svc = _drive_service_or_503()
    summaries: list[dict[str, Any]] = []
    for f in files:
        name = (f.filename or "upload").strip() or "upload"
        raw = await f.read()
        if not raw:
            summaries.append({"filename": name, "status": "error", "detail": "empty"})
            continue
        if len(raw) > MAX_DRIVE_STAGE_UPLOAD:
            summaries.append(
                {
                    "filename": name,
                    "status": "error",
                    "detail": f"fișier prea mare (max {MAX_DRIVE_STAGE_UPLOAD // (1024 * 1024)} MiB)",
                }
            )
            continue
        mime = (f.content_type or "").strip() or None
        try:
            created = drive_google.upload_file_to_folder(
                svc,
                folder_id=settings.stage_folder_id,
                filename=name,
                content=raw,
                mime_type=mime,
            )
        except Exception as e:  # noqa: BLE001
            summaries.append({"filename": name, "status": "error", "detail": str(e)})
            continue
        fid = str(created.get("id") or "")
        summaries.append(
            {
                "filename": name,
                "status": "ok",
                "file_id": fid,
                "webViewLink": created.get("webViewLink"),
                "web_link": drive_google.drive_file_web_link(fid) if fid else None,
                "mimeType": created.get("mimeType"),
            }
        )
    ok_n = sum(1 for x in summaries if x.get("status") == "ok")
    err_n = len(summaries) - ok_n
    log.info(
        "drive.stage_upload parts=%s ok=%s err=%s ms=%.1f",
        len(summaries),
        ok_n,
        err_n,
        (time.perf_counter() - t0) * 1000,
    )
    return {"ok": True, "stage_folder_id": settings.stage_folder_id, "files": summaries}


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


class DriveBatchAutoOrganizeRequest(BaseModel):
    """Parcurge un folder Drive și copiază fiecare fișier în subfolderul bibliotecii după extensie."""

    source_folder_id: str | None = Field(
        default=None,
        max_length=256,
        description="ID folder sursă. Gol = folderul Stage din .env.",
    )
    recursive: bool = Field(
        default=False,
        description="Dacă true, include toate fișierele din subfoldere (BFS). Nu folosi pe rădăcina bibliotecii.",
    )
    max_files: int = Field(
        default=150,
        ge=1,
        le=500,
        description="Limită per cerere (evită timeout HTTP). Pentru mii de fișiere folosește scriptul CLI.",
    )
    ingest_to_rag: bool = Field(
        default=False,
        description="După fiecare copiere reușită, indexează în Chroma (mai lent).",
    )
    pause_sec: float = Field(
        default=0.06,
        ge=0.0,
        le=2.0,
        description="Pauză scurtă între fișiere (reduce presiunea pe cotele Drive API).",
    )


class WizardAutoPlaceRequest(BaseModel):
    """După upload în Stage: plasare automată după extensie pentru lista de file_id."""

    source_file_ids: list[str] = Field(
        ...,
        min_length=1,
        max_length=WIZARD_AUTO_PLACE_MAX_IDS,
        description=f"Lista de Google file_id din Stage (max {WIZARD_AUTO_PLACE_MAX_IDS} pe cerere; UI-ul face mai multe cereri).",
    )
    ingest_to_rag: bool = Field(
        default=False,
        description="După fiecare copiere reușită, indexează în Chroma.",
    )


@app.post(
    "/drive/wizard/auto-place",
    tags=["drive"],
    summary="Plasare automată wizard (max ID-uri / cerere)",
    description=(
        f"Primește până la {WIZARD_AUTO_PLACE_MAX_IDS} `source_file_id` per cerere (clasificare după extensie, copiere în bibliotecă). "
        "Interfața web împarte automat listele mai lungi în mai multe cereri. Pentru mii de fișiere dintr-un folder, "
        "vezi `POST /drive/batch/auto-organize` sau scriptul `scripts/drive_batch_auto_organize.py`."
    ),
)
def drive_wizard_auto_place(req: WizardAutoPlaceRequest) -> dict[str, Any]:
    settings, svc = _drive_service_or_503()
    t0 = time.perf_counter()
    ids = list(dict.fromkeys([(x or "").strip() for x in req.source_file_ids if (x or "").strip()]))
    if not ids:
        raise HTTPException(status_code=422, detail="source_file_ids este gol după filtrare.")
    out = auto_place_uploaded_file_ids(
        svc,
        settings,
        source_file_ids=ids,
        ingest_to_rag=req.ingest_to_rag,
        rag=rag,
    )
    log.info(
        "drive.wizard_auto_place ids=%s ms=%.1f ingest_rag=%s",
        len(ids),
        (time.perf_counter() - t0) * 1000,
        req.ingest_to_rag,
    )
    return out


@app.post("/drive/batch/auto-organize", tags=["drive"])
def drive_batch_auto_organize(req: DriveBatchAutoOrganizeRequest) -> dict[str, Any]:
    """
    Flux fără pași manuali: citește fișierele din folder, pentru fiecare alege PDF/Documente/Afise/Powerpoint/Altele,
    creează subfolderele lipsă sub bibliotecă și copiază. Omite fișierele deja înregistrate în memoria de copieri.
    """
    settings, svc = _drive_service_or_503()
    src = (req.source_folder_id or "").strip() or settings.stage_folder_id
    out = batch_auto_organize_from_folder(
        svc,
        settings,
        source_folder_id=src,
        recursive=req.recursive,
        max_files=req.max_files,
        ingest_to_rag=req.ingest_to_rag,
        rag=rag,
        pause_sec=req.pause_sec,
    )
    if not out.get("ok"):
        raise HTTPException(status_code=400, detail=out.get("detail") or "batch failed")
    return out


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
        "hint": "POST /ingest/files, POST /chat, GET /search, POST /archive/page, GET /drive/status, POST /drive/wizard/auto-place, POST /drive/batch/auto-organize — vezi README.",
    }
