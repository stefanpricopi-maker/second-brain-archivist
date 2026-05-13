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


def test_chunk_readability_prefers_coherent_ocr() -> None:
    from app.main import _chunk_readability

    good = (
        "„Mai ușor este să treacă o cămilă prin urechea acului decât să intre un om bogat "
        "în Împărăția lui Dumnezeu” (Luca 18:25) se construiește pe ideea dificultății."
    )
    bad = "i a sina 139 ÎNCA asi aa A A aaa aa 140 iii Pi aia Ra a PA .. Slatinei 0 PIPI II"
    assert _chunk_readability(good) > _chunk_readability(bad)
    assert _chunk_readability(good) >= 0.33


def test_fallback_answer_plain_no_meta_markdown() -> None:
    from app.main import _fallback_answer

    chunks = [
        {
            "text": (
                "Ion merge la poartă și deschide ușa încet. Soarele strălucea pe dealurile "
                "verzi din jurul satului."
            ),
            "metadata": {"source": "poveste.pdf", "page": 2},
        },
    ]
    s = _fallback_answer("Ce face Ion la poartă?", chunks, source="poveste.pdf")
    assert "**" not in s
    assert "rezumat" not in s.lower()
    assert "LLM_MODE" not in s
    assert "pag." not in s.lower()
    assert "ion" in s.lower()


def test_chat_accepts_source_field(client: TestClient) -> None:
    r = client.post(
        "/chat",
        json={"message": "Ce conține cartea?", "k": 4, "source": "missing.pdf"},
    )
    assert r.status_code == 200
    body = r.json()
    assert "answer" in body
    ans = body["answer"].lower()
    assert (
        "missing.pdf" in ans
        or "rezumat" in ans
        or "nu am găsit" in ans
        or "nu am putut extrage" in ans
        or "fragment" in ans
        or "index" in ans
    )
