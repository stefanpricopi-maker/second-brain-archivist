from __future__ import annotations

import pytest
from starlette.testclient import TestClient


@pytest.fixture
def client() -> TestClient:
    from app.main import app

    return TestClient(app)


def test_health(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json().get("status") == "ok"


def test_status(client: TestClient) -> None:
    r = client.get("/status")
    assert r.status_code == 200
    data = r.json()
    assert "rag_chunks" in data
    assert data.get("llm_mode") in ("disabled", "openai")
    arch = data.get("archive") or {}
    assert "notion_configured" in arch
    assert arch.get("mode") in ("obsidian", "notion", "download")

def test_static_ui_served(client: TestClient) -> None:
    r = client.get("/static/index.html")
    assert r.status_code == 200
    assert "Arhivist" in r.text
    assert "Second Brain" in r.text
    assert "/static/css/app.css" in r.text
    assert "/static/js/app.js" in r.text
    assert "wizardCardResult" in r.text
    assert "wizardPipelineWrap" in r.text
    assert "/drive/wizard/auto-place" in r.text


def test_static_ui_assets(client: TestClient) -> None:
    assert client.get("/static/css/app.css").status_code == 200
    assert client.get("/static/js/app.js").status_code == 200


def test_search_requires_q(client: TestClient) -> None:
    r = client.get("/search", params={"k": 5})
    assert r.status_code in (400, 422)


def test_search_empty_index_ok(client: TestClient) -> None:
    r = client.get("/search", params={"q": "stoicism", "k": 3})
    assert r.status_code == 200
    data = r.json()
    assert data.get("query") == "stoicism"
    assert isinstance(data.get("results"), list)


def test_chat_fallback(client: TestClient) -> None:
    r = client.post(
        "/chat",
        json={"message": "Ce spune Marcus Aurelius despre eșec?", "k": 4},
    )
    assert r.status_code == 200
    body = r.json()
    assert "answer" in body
    assert len(body["answer"]) > 20


def test_archive_creates_download_link(client: TestClient) -> None:
    r = client.post(
        "/archive/page",
        json={
            "title": "Plan dimineață — eșec",
            "body_markdown": "## Focus\n- respirație\n- o pagină citit",
            "subdirectory": "Journal/Test",
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data.get("ok") is True
    assert data.get("destination") in ("download", "obsidian")
    if data.get("destination") == "download":
        p = str(data.get("path_or_url") or "")
        assert p.startswith("/archive/files/")
