from __future__ import annotations

import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.connectors import BrowserDownloadSink, ObsidianVaultSink
from app.connectors.notion_api import load_notion_sink_from_env
from app import ingest_jobs
from app.ingest_service import ingest_main_files, ingest_voice_pdf_batch
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
from openai import (
    APIError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    OpenAI,
    RateLimitError,
)

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


def openai_chat_error_to_http(exc: BaseException) -> HTTPException:
    """
    Traduce erorile SDK OpenAI (chat) în HTTP cu mesaj lizibil în română,
    fără a expune corpul JSON complet de la furnizor (ex. 429 insufficient_quota).
    """
    quota_msg = (
        "OpenAI a respins cererea: limită de cotă sau de frecvență (HTTP 429). "
        "Verifică planul și facturarea: https://platform.openai.com/account/billing — "
        "sau pune în `.env` LLM_MODE=disabled și repornește serverul pentru răspunsuri locale "
        "din fragmente RAG (fără sinteză LLM)."
    )
    if isinstance(exc, AuthenticationError):
        return HTTPException(
            status_code=401,
            detail="OpenAI: cheie API invalidă sau refuzată. Verifică OPENAI_API_KEY în `.env`.",
        )
    if isinstance(exc, APITimeoutError):
        return HTTPException(
            status_code=504,
            detail="OpenAI: timeout la apel. Încearcă din nou sau verifică rețeaua.",
        )
    if isinstance(exc, RateLimitError):
        return HTTPException(status_code=503, detail=quota_msg)
    if isinstance(exc, BadRequestError):
        brief = (getattr(exc, "message", None) or str(exc))[:400]
        return HTTPException(
            status_code=400,
            detail=f"OpenAI: cerere invalidă. {brief}",
        )
    if isinstance(exc, APIStatusError):
        status = int(getattr(exc, "status_code", 0) or 0)
        body = getattr(exc, "body", None)
        inner_code = None
        if isinstance(body, dict):
            err = body.get("error")
            if isinstance(err, dict):
                inner_code = err.get("code") or err.get("type")
        if status == 429 or inner_code == "insufficient_quota":
            return HTTPException(status_code=503, detail=quota_msg)
        brief = (getattr(exc, "message", None) or str(exc))[:450]
        return HTTPException(status_code=502, detail=f"OpenAI API ({status}): {brief}")
    if isinstance(exc, APIError):
        brief = (getattr(exc, "message", None) or str(exc))[:450]
        return HTTPException(status_code=502, detail=f"OpenAI: {brief}")
    return HTTPException(status_code=502, detail=f"Eroare LLM: {exc}")


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


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> FileResponse:
    """Evită 404 în consola browserului la încărcarea paginii."""
    path = STATIC_DIR / "favicon.ico"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="favicon missing")
    return FileResponse(str(path), media_type="image/vnd.microsoft.icon", filename="favicon.ico")


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
        "openai_key_configured": _has_openai_key,
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
    dry_run: bool = False


def _squish_ws(text: str) -> str:
    return " ".join((text or "").split())


def _truncate_words(text: str, max_chars: int) -> str:
    t = _squish_ws(text).strip()
    if not t:
        return ""
    if len(t) <= max_chars:
        return t
    cut = t[: max_chars - 3].rstrip()
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.strip() + "..."


def _chunk_has_query_overlap(raw: str, q_tokens: list[str]) -> bool:
    """True dacă textul fragmentului conține explicit un termen din întrebare (nu doar similaritate vectorială)."""
    if not q_tokens:
        return True
    lower = _squish_ws(raw).lower()
    return any(tok in lower for tok in q_tokens)


def _query_tokens_for_fallback(query: str) -> list[str]:
    """Termeni din întrebare pentru potrivire lexicală în modul fără LLM (inclusiv cuvinte scurte utile în RO)."""
    stop = frozenset(
        """
        și sau fie ca la de cu pe în un o unei unul oarecare ce care cum când cât câte câți câteva
        este sunt era erau fi fost fiind am ai au aș vei vom vor fi eu tu el ea noi voi ei ele
        a ai ale al lui ei lor să te mă îți îmi ne miți mi vă ne-ți ne-am
        da nu da nu ok ba deci doar tot foarte mult mai mult mai puțin
        the and or of to in is are was were be been being
        """.split()
    )
    out: list[str] = []
    for w in _squish_ws(query).lower().split():
        w = w.strip(".,?!:;\"'«»()[]{}—–-")
        if len(w) < 2 or w in stop:
            continue
        if w not in out:
            out.append(w)
        if len(out) >= 14:
            break
    return out


def _pick_excerpt(raw: str, query_tokens: list[str], *, max_chars: int) -> str:
    """Extras scurt; dacă întrebarea conține termeni lungi, preferă fereastra din jurul unui potrivit."""
    t = _squish_ws(raw)
    if not t:
        return ""
    lower = t.lower()
    pad = min(100, max_chars + 35)
    for tok in query_tokens:
        if tok in lower:
            idx = lower.find(tok)
            start = max(0, idx - min(50, max_chars // 2))
            window = t[start : start + max_chars + pad]
            return _truncate_words(window, max_chars)
    return _truncate_words(t, max_chars)


def _chunk_readability(text: str) -> float:
    """Scor 0–1 pentru text OCR: favorizează propoziții cu litere și cuvinte medii/lungi, penalizează zgomot."""
    t = _squish_ws(text or "")
    n = len(t)
    if n < 14:
        return 0.06
    letters = sum(1 for c in t if c.isalpha())
    lr = letters / max(n, 1)
    score = lr
    if lr < 0.38:
        score *= 0.45
    elif lr < 0.48:
        score *= 0.72
    words = t.split()
    nw = len(words)
    if nw < 2:
        return 0.05
    singles = sum(1 for w in words if len(w) == 1)
    awl = sum(len(w) for w in words) / nw
    if nw >= 9 and singles / nw > 0.14:
        score *= 0.35
    if awl < 2.75 and nw >= 10:
        score *= 0.48
    if t.count("|") >= 4:
        score *= 0.55
    if sum(1 for c in t if c.isdigit()) / n > 0.2:
        score *= 0.62
    return float(min(1.0, max(0.0, score)))


def _sort_chunks_for_fallback(chunks: list[dict[str, Any]], q_tokens: list[str]) -> list[dict[str, Any]]:
    """Prioritizează fragmentele care conțin termeni din întrebare, apoi lizibilitatea (OCR)."""

    def key(ch: dict[str, Any]) -> tuple[int, float]:
        raw = ch.get("text") or ""
        overlap = 1 if _chunk_has_query_overlap(raw, q_tokens) else 0
        return (overlap, _chunk_readability(raw))

    return sorted(chunks, key=key, reverse=True)


def _trim_chunks_for_public(chunks: list[dict[str, Any]], *, max_text: int = 240) -> list[dict[str, Any]]:
    """În mod fără LLM, răspunsul JSON nu trebuie să repete tot OCR-ul; metadata rămâne intactă."""
    out: list[dict[str, Any]] = []
    for c in chunks:
        d = dict(c)
        t = d.get("text") or ""
        if len(t) > max_text:
            d["text"] = _truncate_words(t, max_text)
        out.append(d)
    return out


def _fallback_answer(
    query: str,
    chunks: list[dict[str, Any]],
    *,
    source: str | None = None,
    lex_tokens: list[str] | None = None,
) -> str:
    """Răspuns fără apel OpenAI: propoziții simple, fără markdown, potrivit citirii vocale."""
    if not chunks:
        src = (source or "").strip()
        if src:
            return (
                "Nu am găsit în index text despre această întrebare pentru cartea aleasă. "
                "Verifică numele cărții în listă sau indexează din nou cartea. "
                f"Întrebarea ta sună așa: {_squish_ws(query)[:220]}"
            )
        return (
            "Nu am găsit nimic în index. Pune cartea în bibliotecă și rulează scriptul de indexare din documentația proiectului. "
            f"Întrebarea ta: {_squish_ws(query)[:220]}"
        )
    q_tokens = lex_tokens if lex_tokens is not None else _query_tokens_for_fallback(query)
    excerpt_max = 160
    readability_min = 0.36
    max_take = 6
    parts: list[str] = []
    for ch in chunks[:max_take]:
        raw = ch.get("text") or ""
        if _chunk_readability(raw) < readability_min:
            continue
        if q_tokens and not _chunk_has_query_overlap(raw, q_tokens):
            continue
        ex = _pick_excerpt(raw, q_tokens, max_chars=excerpt_max)
        clean = _squish_ws(ex)
        if len(clean) < 36:
            continue
        parts.append(clean)
    if not parts:
        return (
            "Din scanarea acestei cărți nu am putut extrage propoziții clare legate de întrebare. "
            "Încearcă altfel întrebarea sau deschide cartea la citire directă."
        )
    body = ". ".join(parts)
    if body and body[-1] not in ".!?":
        body += "."
    return body


@app.post("/chat", response_model=ChatResponse, tags=["chat"])
def chat(req: ChatRequest) -> ChatResponse:
    query = req.message.strip()
    where = _metadata_source_filter(req.source)
    chunks = rag.query(query, k=req.k, where=where)
    if LLM_MODE != "openai" or client is None:
        qt = _query_tokens_for_fallback(query)
        ranked = _sort_chunks_for_fallback(chunks, qt)
        return ChatResponse(
            answer=_fallback_answer(query, ranked, source=req.source, lex_tokens=qt),
            used_chunks=_trim_chunks_for_public(ranked),
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
                        "Ești arhivistul unei biblioteci personale. Răspunde în limba utilizatorului. "
                        "Bazează-te doar pe fragmentele primite; nu inventa citate. "
                        "Scrie strict în propoziții uzuale, fără markdown, fără liste cu liniuță sau stea, "
                        "fără JSON, fără antete gen «Rezumat», fără numere de pagină în text — potrivit pentru citire vocală."
                    ),
                },
                {"role": "user", "content": user_block},
            ],
        )
    except (AuthenticationError, RateLimitError, BadRequestError, APIStatusError, APITimeoutError, APIError) as e:
        raise openai_chat_error_to_http(e) from e
    except Exception as e:
        log.warning("chat LLM unexpected error: %s", e, exc_info=True)
        raise HTTPException(status_code=502, detail=f"Eroare LLM neașteptată: {e}") from e

    answer = (r.choices[0].message.content or "").strip()
    if not answer:
        raise HTTPException(status_code=502, detail="Empty LLM response")
    return ChatResponse(answer=answer, used_chunks=chunks)

@app.post("/ingest/files", response_model=IngestResponse, tags=["library"])
async def ingest_files(
    dry_run: bool = Form(False),
    files: list[UploadFile] = File(...),
) -> IngestResponse:
    items: list[tuple[str, bytes]] = []
    for f in files:
        raw = await f.read()
        name = (f.filename or "upload").strip() or "upload"
        items.append((name, raw))
    out = ingest_main_files(rag, UPLOADS_DIR, items, dry_run=dry_run, progress=None)
    return IngestResponse(**out)


@app.post("/ingest/jobs", tags=["library"], summary="Indexare asincronă cu progres SSE")
async def ingest_jobs_create(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
) -> dict[str, Any]:
    """Încarcă fișierele; procesarea RAG rulează în fundal. Urmărește `GET /ingest/jobs/{id}/events` (SSE)."""
    items: list[tuple[str, bytes]] = []
    for f in files:
        raw = await f.read()
        name = (f.filename or "upload").strip() or "upload"
        items.append((name, raw))
    job_id = ingest_jobs.create_job(kind="main")
    background_tasks.add_task(
        ingest_jobs.run_main_ingest_job,
        job_id,
        items,
        uploads_dir=UPLOADS_DIR,
        rag=rag,
    )
    return {
        "job_id": job_id,
        "status_url": f"/ingest/jobs/{job_id}",
        "events_url": f"/ingest/jobs/{job_id}/events",
    }


@app.get("/ingest/jobs/{job_id}", tags=["library"])
def ingest_job_status(job_id: str) -> dict[str, Any]:
    st = ingest_jobs.job_snapshot(job_id)
    if st is None:
        raise HTTPException(status_code=404, detail="Job inexistent.")
    return st


@app.get("/ingest/jobs/{job_id}/events", tags=["library"])
async def ingest_job_events(job_id: str) -> StreamingResponse:
    if ingest_jobs.job_snapshot(job_id) is None:
        raise HTTPException(status_code=404, detail="Job inexistent.")
    return StreamingResponse(
        ingest_jobs.sse_iter_job(job_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
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


@app.delete(
    "/voice-library/index",
    tags=["voice_library"],
    summary="Șterge din RAG toate fragmentele unei surse",
    description=(
        "Query: `source` — exact aceeași valoare ca în metadata (numele fișierului din listă, ex. «carte.pdf»). "
        "După ștergere, re-indexează cartea dacă vrei din nou în RAG."
    ),
)
def voice_library_delete_index(source: str) -> dict[str, Any]:
    s = (source or "").strip()
    if not s:
        raise HTTPException(status_code=422, detail="Parametrul «source» e obligatoriu.")
    if len(s) > 512:
        raise HTTPException(status_code=422, detail="Parametrul «source» e prea lung (max 512).")
    deleted = rag.delete_by_source(source=s)
    return {
        "ok": True,
        "source": s,
        "deleted_chunks": deleted,
        "rag_chunks": rag.count(),
    }


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
    dry_run: bool = Form(False),
) -> IngestResponse:
    items: list[tuple[str, bytes]] = []
    for f in files:
        raw = await f.read()
        name = (f.filename or "upload").strip() or "upload"
        items.append((name, raw))
    out = ingest_voice_pdf_batch(
        rag,
        UPLOADS_DIR,
        items,
        book_label=(book_label or "").strip() or None,
        force_ocr=force_ocr,
        dry_run=dry_run,
        progress=None,
    )
    return IngestResponse(**out)


@app.post("/voice-library/jobs", tags=["voice_library"], summary="Încărcare PDF + OCR/index asincron cu SSE")
async def voice_library_jobs_create(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    book_label: str = Form(""),
    force_ocr: str = Form("auto"),
) -> dict[str, Any]:
    items: list[tuple[str, bytes]] = []
    for f in files:
        raw = await f.read()
        name = (f.filename or "upload").strip() or "upload"
        items.append((name, raw))
    job_id = ingest_jobs.create_job(kind="voice")
    background_tasks.add_task(
        ingest_jobs.run_voice_ingest_job,
        job_id,
        items,
        uploads_dir=UPLOADS_DIR,
        rag=rag,
        book_label=(book_label or "").strip() or None,
        force_ocr=(force_ocr or "auto").strip(),
    )
    return {
        "job_id": job_id,
        "status_url": f"/voice-library/jobs/{job_id}",
        "events_url": f"/voice-library/jobs/{job_id}/events",
    }


@app.get("/voice-library/jobs/{job_id}", tags=["voice_library"])
def voice_library_job_status(job_id: str) -> dict[str, Any]:
    st = ingest_jobs.job_snapshot(job_id)
    if st is None:
        raise HTTPException(status_code=404, detail="Job inexistent.")
    return st


@app.get("/voice-library/jobs/{job_id}/events", tags=["voice_library"])
async def voice_library_job_events(job_id: str) -> StreamingResponse:
    if ingest_jobs.job_snapshot(job_id) is None:
        raise HTTPException(status_code=404, detail="Job inexistent.")
    return StreamingResponse(
        ingest_jobs.sse_iter_job(job_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
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


@app.get("/meta", tags=["meta"], summary="Rezumat serviciu (JSON)")
def service_meta() -> dict[str, str]:
    return {
        "service": "second-brain-archivist",
        "docs": "/docs",
        "ui": "/static/index.html",
        "hint": "POST /ingest/files, POST /chat, GET /search, POST /archive/page, GET /drive/status, POST /drive/wizard/auto-place, POST /drive/batch/auto-organize — vezi README.",
    }


@app.get("/", tags=["meta"], summary="Deschide UI-ul")
def root() -> RedirectResponse:
    return RedirectResponse(url="/static/index.html", status_code=302)
