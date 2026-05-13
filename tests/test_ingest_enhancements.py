from __future__ import annotations

import time
import uuid

import pytest
from starlette.testclient import TestClient


@pytest.fixture
def client() -> TestClient:
    from app.main import app

    return TestClient(app)


def test_ingest_dry_run_would_ingest(client: TestClient) -> None:
    name = f"dry-{uuid.uuid4().hex[:8]}.md"
    r = client.post(
        "/ingest/files",
        data={"dry_run": "true"},
        files=[("files", (name, b"# Titlu\n\nParagraf unic.", "text/markdown"))],
    )
    assert r.status_code == 200
    j = r.json()
    assert j.get("dry_run") is True
    rows = j.get("files") or []
    assert rows and rows[0].get("status") in ("would_ingest", "skipped_unchanged")


def test_ingest_job_completes(client: TestClient) -> None:
    name = f"job-{uuid.uuid4().hex[:8]}.md"
    r = client.post(
        "/ingest/jobs",
        files=[("files", (name, b"# J\n\nText unic pentru job ingest.", "text/markdown"))],
    )
    assert r.status_code == 200
    job_id = r.json().get("job_id")
    assert job_id
    deadline = time.monotonic() + 15.0
    last = None
    while time.monotonic() < deadline:
        s = client.get(f"/ingest/jobs/{job_id}")
        assert s.status_code == 200
        last = s.json()
        if last.get("status") == "done":
            break
        if last.get("status") == "error":
            raise AssertionError(last.get("error") or last)
        time.sleep(0.05)
    assert last is not None
    assert last.get("status") == "done"
    res = last.get("result") or {}
    assert isinstance(res.get("files"), list)


def test_voice_library_dry_run(client: TestClient) -> None:
    name = f"v-{uuid.uuid4().hex[:8]}.pdf"
    r = client.post(
        "/voice-library/ingest",
        data={"book_label": "", "force_ocr": "auto", "dry_run": "true"},
        files=[("files", (name, b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj<<>>endobj trailer<<>>\n%%EOF", "application/pdf"))],
    )
    assert r.status_code == 200
    j = r.json()
    assert j.get("dry_run") is True
