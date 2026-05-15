from __future__ import annotations

from pathlib import Path

import pytest

from app.rag import LibraryRAGIndex, query_tokens_for_match


@pytest.fixture
def rag(tmp_path: Path) -> LibraryRAGIndex:
    return LibraryRAGIndex(persist_dir=tmp_path / "vs")


def test_query_tokens_skips_stopwords() -> None:
    t = query_tokens_for_match("Ce spune Marcus despre eșec?")
    assert "marcus" in t or "eșec" in t or "spune" in t
    assert "ce" not in t


def test_query_expanded_prefers_lexical_match(rag: LibraryRAGIndex, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_FETCH_MULTIPLIER", "2")
    monkeypatch.setenv("RAG_FETCH_MAX", "10")
    monkeypatch.setenv("RAG_LEXICAL_WEIGHT", "0.35")
    texts = [
        "Stoicismul în Roma antică și virtutea civică.",
        "Rețete de pâine cu maia — coacere lentă.",
        "Marcus Aurelius vorbește despre eșec și reziliență în Meditații.",
        "Marcus Aurelius repetă tema eșecului în alt capitol.",
        "Astronomie: orbite planetare.",
    ]
    rag.add_texts(
        ids=[f"id-{i}" for i in range(len(texts))],
        texts=texts,
        metadatas=[{"source": f"f{i}.pdf", "chunk": i} for i in range(len(texts))],
    )
    hits = rag.query_expanded("Marcus Aurelius eșec", k=3)
    assert len(hits) == 3
    joined = " ".join(h.get("text") or "" for h in hits).lower()
    assert "marcus" in joined or "eșec" in joined
    # MMR: nu ar trebui toate cele 3 să fie doar duplicate aproape identice
    assert len({h.get("text") for h in hits}) >= 2


def test_query_expanded_respects_source_filter(rag: LibraryRAGIndex) -> None:
    rag.add_texts(
        ids=["a", "b"],
        texts=["alpha stoicism text", "beta stoicism text"],
        metadatas=[{"source": "a.pdf"}, {"source": "b.pdf"}],
    )
    hits = rag.query_expanded("stoicism", k=2, where={"source": {"$eq": "a.pdf"}})
    assert len(hits) == 1
    assert hits[0]["metadata"]["source"] == "a.pdf"


def test_query_delegates_to_expanded_by_default(rag: LibraryRAGIndex, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_QUERY_EXPANDED", "1")
    rag.add_texts(ids=["x"], texts=["unic test fragment"], metadatas=[{"source": "t.md"}])
    hits = rag.query("unic test", k=1)
    assert len(hits) == 1
    assert "unic" in (hits[0].get("text") or "").lower()


def test_query_simple_when_expanded_disabled(rag: LibraryRAGIndex, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_QUERY_EXPANDED", "0")
    rag.add_texts(ids=["x"], texts=["alpha beta"], metadatas=[{"source": "t.md"}])
    hits = rag.query("alpha", k=1)
    assert len(hits) == 1
