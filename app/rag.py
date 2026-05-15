from __future__ import annotations

import math
import os
import warnings
from pathlib import Path
from typing import Any

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    import chromadb  # noqa: E402

_QUERY_STOP = frozenset(
    """
    și sau fie ca la de cu pe în un o unei unul oarecare ce care cum când cât câte câți câteva
    este sunt era erau fi fost fiind am ai au aș vei vom vor fi eu tu el ea noi voi ei ele
    a ai ale al lui ei lor să te mă îți îmi ne miți mi vă ne-ți ne-am
    da nu ok ba deci doar tot foarte mult mai mult mai puțin
    the and or of to in is are was were be been being
    """.split()
)


def _squish_ws(text: str) -> str:
    return " ".join((text or "").split())


def query_tokens_for_match(query: str, *, max_tokens: int = 14) -> list[str]:
    """Termeni din întrebare pentru potrivire lexicală (RO + EN stopwords uzuale)."""
    out: list[str] = []
    for w in _squish_ws(query).lower().split():
        w = w.strip(".,?!:;\"'«»()[]{}—–-")
        if len(w) < 2 or w in _QUERY_STOP:
            continue
        if w not in out:
            out.append(w)
        if len(out) >= max_tokens:
            break
    return out


def _lexical_overlap_score(text: str, tokens: list[str]) -> float:
    if not tokens:
        return 0.0
    lower = _squish_ws(text).lower()
    hits = sum(1 for t in tokens if t in lower)
    return hits / len(tokens)


def _embedding_as_list(emb: Any) -> list[float] | None:
    if emb is None:
        return None
    try:
        if hasattr(emb, "tolist"):
            emb = emb.tolist()
        return [float(x) for x in emb]
    except (TypeError, ValueError):
        return None


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return dot / (na * nb)


def _env_bool(name: str, default: bool) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _mmr_select(
    items: list[dict[str, Any]],
    *,
    k: int,
    lambda_mult: float,
) -> list[dict[str, Any]]:
    """
    Maximal Marginal Relevance pe candidații deja scorați (câmp `relevance` 0..1).
    Fiecare item trebuie să aibă `embedding` (list[float]) sau se folosește doar relevance.
    """
    if not items or k <= 0:
        return []
    pool = list(items)
    lam = max(0.0, min(1.0, lambda_mult))
    selected: list[dict[str, Any]] = []
    while pool and len(selected) < k:
        best_idx = 0
        best_score = -1e9
        for i, cand in enumerate(pool):
            rel = float(cand.get("relevance") or 0.0)
            if not selected:
                mmr = rel
            else:
                emb_c = cand.get("embedding")
                max_sim = 0.0
                if isinstance(emb_c, list) and emb_c:
                    for sel in selected:
                        emb_s = sel.get("embedding")
                        if isinstance(emb_s, list) and emb_s:
                            max_sim = max(max_sim, _cosine_similarity(emb_c, emb_s))
                mmr = lam * rel - (1.0 - lam) * max_sim
            if mmr > best_score:
                best_score = mmr
                best_idx = i
        selected.append(pool.pop(best_idx))
    return selected


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
        """Upsert: re-indexarea aceluiași `id` înlocuiește documentul (re-ingest cu același id stabil)."""
        self.collection.upsert(ids=ids, documents=texts, metadatas=metadatas)

    def get_bytes_sha_for_source(self, *, source: str) -> str | None:
        """Primul `bytes_sha256` găsit pentru sursă (toate fragmentele din același ingest îl împărtășesc)."""
        src = (source or "").strip()
        if not src:
            return None
        got = self.collection.get(
            where={"source": {"$eq": src}},
            limit=1,
            include=["metadatas"],
        )
        metas = got.get("metadatas") or []
        if not metas:
            return None
        md = metas[0] or {}
        v = md.get("bytes_sha256")
        return str(v).strip() if v else None

    def _raw_query(
        self,
        query: str,
        n_results: int,
        *,
        where: dict[str, Any] | None = None,
        include_embeddings: bool = False,
    ) -> dict[str, Any]:
        n = max(1, int(n_results))
        include = ["documents", "metadatas", "distances"]
        if include_embeddings:
            include.append("embeddings")
        kwargs: dict[str, Any] = {
            "query_texts": [query],
            "n_results": n,
            "include": include,
        }
        if where:
            kwargs["where"] = where
        return self.collection.query(**kwargs)

    def query(self, query: str, k: int, where: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Căutare RAG; implicit folosește `query_expanded` dacă RAG_QUERY_EXPANDED nu e dezactivat."""
        if _env_bool("RAG_QUERY_EXPANDED", True):
            return self.query_expanded(query, k, where=where)
        return self._query_simple(query, k, where=where)

    def _query_simple(self, query: str, k: int, where: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if self.collection.count() == 0:
            return []
        res = self._raw_query(query, max(1, int(k)), where=where, include_embeddings=False)
        docs = (res.get("documents") or [[]])[0]
        metas = (res.get("metadatas") or [[]])[0]
        out: list[dict[str, Any]] = []
        for text, md in zip(docs, metas):
            out.append({"text": text, "metadata": md or {}})
        return out

    def query_expanded(
        self,
        query: str,
        k: int,
        *,
        where: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Retrieve extins: mai mulți candidați din Chroma → scor semantic + lexical → MMR → top k.

        Env: RAG_FETCH_MULTIPLIER (3), RAG_FETCH_MAX (48), RAG_MMR_LAMBDA (0.7), RAG_LEXICAL_WEIGHT (0.2).
        """
        q = (query or "").strip()
        if not q or self.collection.count() == 0:
            return []
        k = max(1, int(k))
        mult = max(1, _env_int("RAG_FETCH_MULTIPLIER", 3))
        fetch_cap = max(k, _env_int("RAG_FETCH_MAX", 48))
        n_fetch = min(int(self.collection.count()), min(fetch_cap, k * mult))
        lam = _env_float("RAG_MMR_LAMBDA", 0.7)
        lex_w = max(0.0, min(0.5, _env_float("RAG_LEXICAL_WEIGHT", 0.2)))

        res = self._raw_query(q, n_fetch, where=where, include_embeddings=True)
        docs = (res.get("documents") or [[]])[0] or []
        metas = (res.get("metadatas") or [[]])[0] or []
        dists = (res.get("distances") or [[]])[0] or []
        raw_embs = res.get("embeddings")
        row_embs: list[Any] = []
        if raw_embs is not None and len(raw_embs) > 0 and raw_embs[0] is not None:
            row_embs = list(raw_embs[0])

        tokens = query_tokens_for_match(q)
        candidates: list[dict[str, Any]] = []
        for i, text in enumerate(docs):
            if text is None:
                continue
            md = metas[i] if i < len(metas) else {}
            dist = float(dists[i]) if i < len(dists) and dists[i] is not None else 1.0
            # Chroma cosine distance: 0 = identic, 2 = opus; mapăm la relevance 0..1
            sem = max(0.0, 1.0 - min(dist, 2.0) / 2.0)
            lex = _lexical_overlap_score(str(text), tokens)
            relevance = (1.0 - lex_w) * sem + lex_w * lex
            emb = _embedding_as_list(row_embs[i]) if i < len(row_embs) else None
            candidates.append(
                {
                    "text": text,
                    "metadata": md or {},
                    "relevance": relevance,
                    "embedding": emb,
                    "_scores": {"semantic": sem, "lexical": lex, "distance": dist},
                }
            )

        if not candidates:
            return []

        ranked = _mmr_select(candidates, k=k, lambda_mult=lam)
        out: list[dict[str, Any]] = []
        for item in ranked:
            row: dict[str, Any] = {"text": item["text"], "metadata": item.get("metadata") or {}}
            if item.get("_scores"):
                row["retrieval_scores"] = item["_scores"]
            out.append(row)
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
            if md.get("source_type") == "scanned_pdf" or md.get("ocr") or md.get("scan_derived"):
                row["scanned_pdf"] = True
            if md.get("voice_shelf"):
                row["voice_shelf"] = True
        out = list(agg.values())
        out.sort(key=lambda x: (-int(x.get("chunks") or 0), str(x.get("source") or "")))
        return out

    def delete_by_source(self, *, source: str) -> int:
        """Șterge toate fragmentele cu metadata `source` egală (exact) cu `source`. Returnează numărul de ID-uri șterse."""
        src = (source or "").strip()
        if not src:
            return 0
        total = 0
        where: dict[str, Any] = {"source": {"$eq": src}}
        batch_limit = 2000
        while True:
            batch = self.collection.get(where=where, limit=batch_limit, include=[])
            ids = batch.get("ids") or []
            if not ids:
                break
            self.collection.delete(ids=ids)
            total += len(ids)
            if len(ids) < batch_limit:
                break
        return total
