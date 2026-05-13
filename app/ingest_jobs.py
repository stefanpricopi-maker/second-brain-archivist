from __future__ import annotations

import asyncio
import json
import threading
import uuid
from pathlib import Path
from typing import Any

from fastapi.concurrency import run_in_threadpool

from app.ingest_service import ingest_main_files, ingest_voice_pdf_batch

_lock = threading.Lock()
_JOBS: dict[str, dict[str, Any]] = {}


def job_snapshot(job_id: str) -> dict[str, Any] | None:
    with _lock:
        st = _JOBS.get(job_id)
        return dict(st) if st else None


def _job_put(job_id: str, **kwargs: Any) -> None:
    with _lock:
        if job_id not in _JOBS:
            return
        _JOBS[job_id].update(kwargs)


def create_job(*, kind: str) -> str:
    job_id = uuid.uuid4().hex
    with _lock:
        _JOBS[job_id] = {
            "job_id": job_id,
            "kind": kind,
            "status": "queued",
            "percent": 0.0,
            "phase": "",
            "message": "",
            "current_file": "",
            "result": None,
            "error": None,
        }
    return job_id


def _progress_sink(job_id: str):
    def cb(ev: dict[str, Any]) -> None:
        pct = ev.get("percent")
        payload: dict[str, Any] = {}
        if pct is not None:
            payload["percent"] = float(min(100.0, max(0.0, float(pct))))
        if "phase" in ev:
            payload["phase"] = str(ev.get("phase") or "")
        if "filename" in ev:
            payload["current_file"] = str(ev.get("filename") or "")
        if payload:
            _job_put(job_id, **payload)

    return cb


async def run_main_ingest_job(
    job_id: str,
    items: list[tuple[str, bytes]],
    *,
    uploads_dir: Path,
    rag: Any,
) -> None:
    def work() -> None:
        _job_put(job_id, status="running", percent=0.0, phase="ingest")
        try:
            out = ingest_main_files(
                rag,
                uploads_dir,
                items,
                dry_run=False,
                progress=_progress_sink(job_id),
            )
            _job_put(job_id, status="done", percent=100.0, phase="done", result=out)
        except Exception as e:  # noqa: BLE001
            _job_put(job_id, status="error", error=str(e), phase="error", percent=100.0)

    await run_in_threadpool(work)


async def run_voice_ingest_job(
    job_id: str,
    items: list[tuple[str, bytes]],
    *,
    uploads_dir: Path,
    rag: Any,
    book_label: str | None,
    force_ocr: str,
) -> None:
    def work() -> None:
        _job_put(job_id, status="running", percent=0.0, phase="ingest")
        try:
            out = ingest_voice_pdf_batch(
                rag,
                uploads_dir,
                items,
                book_label=book_label,
                force_ocr=force_ocr,
                dry_run=False,
                progress=_progress_sink(job_id),
            )
            _job_put(job_id, status="done", percent=100.0, phase="done", result=out)
        except Exception as e:  # noqa: BLE001
            _job_put(job_id, status="error", error=str(e), phase="error", percent=100.0)

    await run_in_threadpool(work)


async def sse_iter_job(job_id: str):
    """Evenimente SSE până la status done sau error (sau job necunoscut)."""
    while True:
        st = job_snapshot(job_id)
        if st is None:
            yield f"data: {json.dumps({'error': 'unknown_job', 'job_id': job_id})}\n\n"
            break
        yield f"data: {json.dumps(st, default=str)}\n\n"
        status = st.get("status")
        if status in ("done", "error"):
            break
        await asyncio.sleep(0.22)
