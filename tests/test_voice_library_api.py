from __future__ import annotations

import pytest
from starlette.testclient import TestClient


@pytest.fixture
def client() -> TestClient:
    from app.main import app

    return TestClient(app)


def test_voice_library_ocr_status(client: TestClient) -> None:
    r = client.get("/voice-library/ocr-status")
    assert r.status_code == 200
    data = r.json()
    assert "ok" in data


def test_voice_library_sources(client: TestClient) -> None:
    r = client.get("/voice-library/sources")
    assert r.status_code == 200
    data = r.json()
    assert data.get("ok") is True
    assert isinstance(data.get("sources"), list)


def test_search_accepts_source_param(client: TestClient) -> None:
    r = client.get("/search", params={"q": "test", "k": 3, "source": "nope.pdf"})
    assert r.status_code == 200
    data = r.json()
    assert data.get("source") == "nope.pdf"
    assert isinstance(data.get("results"), list)


def test_search_source_too_long(client: TestClient) -> None:
    r = client.get("/search", params={"q": "x", "source": "a" * 600})
    assert r.status_code == 422


def test_chat_accepts_source_field(client: TestClient) -> None:
    r = client.post(
        "/chat",
        json={"message": "Ce conține cartea?", "k": 4, "source": "missing.pdf"},
    )
    assert r.status_code == 200
    body = r.json()
    assert "answer" in body
    assert "missing.pdf" in body["answer"] or "fragmente" in body["answer"].lower()
