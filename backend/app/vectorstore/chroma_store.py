"""ChromaDB backed store (optional local alternative to pgvector).

``chromadb`` is intentionally *not* a hard dependency: import errors surface as
a clean RuntimeError so the factory can fall back to the in-memory store.
"""
from __future__ import annotations

from typing import Any, Iterable

from app.config import settings
from app.logging import get_logger
from app.vectorstore.base import SearchHit, VectorRecord, VectorStore

logger = get_logger("ecr.vectorstore.chroma")


class ChromaVectorStore(VectorStore):
    name = "chroma"

    def __init__(self) -> None:
        try:
            import chromadb
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("chromadb is not installed (pip install chromadb)") from exc
        self._client = chromadb.PersistentClient(path=settings.chroma_path)
        self._collections: dict[str, Any] = {}
        logger.info("chroma.ready", path=settings.chroma_path)

    def _collection(self, name: str):
        if name not in self._collections:
            self._collections[name] = self._client.get_or_create_collection(
                name=name, metadata={"hnsw:space": "cosine"}
            )
        return self._collections[name]

    def upsert(self, collection: str, records: Iterable[VectorRecord]) -> int:
        items = list(records)
        if not items:
            return 0
        self._collection(collection).upsert(
            ids=[r.id for r in items],
            embeddings=[r.vector for r in items],
            documents=[r.text for r in items],
            metadatas=[_flatten(r.metadata) for r in items],
        )
        return len(items)

    def search(
        self,
        collection: str,
        query_vector: list[float],
        *,
        k: int = 10,
        min_score: float = 0.0,
        where: dict[str, Any] | None = None,
    ) -> list[SearchHit]:
        result = self._collection(collection).query(
            query_embeddings=[query_vector],
            n_results=max(k * 3, k),
            where=_flatten(where) if where else None,
        )
        hits: list[SearchHit] = []
        ids = (result.get("ids") or [[]])[0]
        docs = (result.get("documents") or [[]])[0]
        metas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        for idx, doc_id in enumerate(ids):
            score = 1.0 - float(distances[idx])
            if score < min_score:
                continue
            hits.append(
                SearchHit(
                    id=doc_id,
                    score=score,
                    text=docs[idx] if idx < len(docs) else "",
                    metadata=dict(metas[idx] or {}) if idx < len(metas) else {},
                )
            )
            if len(hits) >= k:
                break
        return hits

    def count(self, collection: str) -> int:
        return int(self._collection(collection).count())

    def reset(self, collection: str | None = None) -> None:
        names = [collection] if collection else list(self._collections)
        for name in names:
            try:
                self._client.delete_collection(name)
            except Exception:  # pragma: no cover
                pass
            self._collections.pop(name, None)


def _flatten(metadata: dict[str, Any]) -> dict[str, Any]:
    """Chroma only accepts scalar metadata values."""
    clean: dict[str, Any] = {}
    for key, value in (metadata or {}).items():
        if isinstance(value, (str, int, float, bool)):
            clean[key] = value
        elif isinstance(value, (list, tuple)):
            clean[key] = ",".join(str(item) for item in value)
        elif value is not None:
            clean[key] = str(value)
    return clean
