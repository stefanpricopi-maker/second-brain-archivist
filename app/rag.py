from __future__ import annotations

import os
import warnings
from pathlib import Path
from typing import Any

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    import chromadb  # noqa: E402


class LibraryRAGIndex:
    """Index Chroma pentru bibliotecă personală (PDF, MD, TXT) + notițe publice."""

    def __init__(self, persist_dir: Path):
        self.persist_dir = persist_dir
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("XDG_CACHE_HOME", str(self.persist_dir / ".cache"))
        self.client = chromadb.PersistentClient(path=str(self.persist_dir))
        self.collection = self.client.get_or_create_collection(
            name="second_brain_library",
            metadata={"hnsw:space": "cosine"},
        )

    def add_texts(self, *, ids: list[str], texts: list[str], metadatas: list[dict[str, Any]]):
        self.collection.add(ids=ids, documents=texts, metadatas=metadatas)

    def query(self, query: str, k: int) -> list[dict[str, Any]]:
        if self.collection.count() == 0:
            return []
        res = self.collection.query(query_texts=[query], n_results=max(1, k))
        docs = (res.get("documents") or [[]])[0]
        metas = (res.get("metadatas") or [[]])[0]
        out: list[dict[str, Any]] = []
        for text, md in zip(docs, metas):
            out.append({"text": text, "metadata": md or {}})
        return out

    def count(self) -> int:
        return int(self.collection.count())
