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

    def query(self, query: str, k: int, where: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if self.collection.count() == 0:
            return []
        n = max(1, int(k))
        kwargs: dict[str, Any] = {"query_texts": [query], "n_results": n}
        if where:
            kwargs["where"] = where
        res = self.collection.query(**kwargs)
        docs = (res.get("documents") or [[]])[0]
        metas = (res.get("metadatas") or [[]])[0]
        out: list[dict[str, Any]] = []
        for text, md in zip(docs, metas):
            out.append({"text": text, "metadata": md or {}})
        return out

    def count(self) -> int:
        return int(self.collection.count())

    def list_sources(self, *, limit_rows: int = 12_000) -> list[dict[str, Any]]:
        """Agregă surse unice din metadata (pentru UI: alegere carte)."""
        n = int(self.collection.count())
        if n == 0:
            return []
        lim = min(n, int(limit_rows))
        raw = self.collection.get(include=["metadatas"], limit=lim)
        metas = raw.get("metadatas") or []
        agg: dict[str, dict[str, Any]] = {}
        for md in metas:
            if not md:
                continue
            src = md.get("source")
            if not isinstance(src, str) or not src.strip():
                continue
            row = agg.setdefault(
                src,
                {
                    "source": src,
                    "chunks": 0,
                    "book_label": None,
                    "scanned_pdf": False,
                    "voice_shelf": False,
                },
            )
            row["chunks"] = int(row["chunks"]) + 1
            bl = md.get("book_label")
            if isinstance(bl, str) and bl.strip() and not row.get("book_label"):
                row["book_label"] = bl.strip()
            if md.get("source_type") == "scanned_pdf" or md.get("ocr"):
                row["scanned_pdf"] = True
            if md.get("voice_shelf"):
                row["voice_shelf"] = True
        out = list(agg.values())
        out.sort(key=lambda x: (-int(x.get("chunks") or 0), str(x.get("source") or "")))
        return out
