"""In-process numpy vector store - the default for local/PoC runs."""
from __future__ import annotations

import threading
from typing import Any, Iterable

import numpy as np

from app.vectorstore.base import SearchHit, VectorRecord, VectorStore


class InMemoryVectorStore(VectorStore):
    name = "memory"

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._matrix: dict[str, np.ndarray] = {}
        self._records: dict[str, list[VectorRecord]] = {}

    def upsert(self, collection: str, records: Iterable[VectorRecord]) -> int:
        items = list(records)
        if not items:
            return 0
        with self._lock:
            existing = {rec.id: idx for idx, rec in enumerate(self._records.get(collection, []))}
            bucket = self._records.setdefault(collection, [])
            for record in items:
                if record.id in existing:
                    bucket[existing[record.id]] = record
                else:
                    existing[record.id] = len(bucket)
                    bucket.append(record)
            self._matrix[collection] = _normalise(
                np.asarray([r.vector for r in bucket], dtype=np.float32)
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
        with self._lock:
            matrix = self._matrix.get(collection)
            records = list(self._records.get(collection, []))
        if matrix is None or not records:
            return []
        query = np.asarray(query_vector, dtype=np.float32)
        norm = float(np.linalg.norm(query)) or 1.0
        scores = matrix @ (query / norm)
        order = np.argsort(-scores)
        hits: list[SearchHit] = []
        for idx in order:
            record = records[int(idx)]
            score = float(scores[int(idx)])
            if score < min_score:
                break
            if where and any(record.metadata.get(key) != value for key, value in where.items()):
                continue
            hits.append(
                SearchHit(id=record.id, score=score, text=record.text, metadata=record.metadata)
            )
            if len(hits) >= k:
                break
        return hits

    def count(self, collection: str) -> int:
        with self._lock:
            return len(self._records.get(collection, []))

    def reset(self, collection: str | None = None) -> None:
        with self._lock:
            if collection is None:
                self._matrix.clear()
                self._records.clear()
            else:
                self._matrix.pop(collection, None)
                self._records.pop(collection, None)

    def health(self) -> dict[str, Any]:
        with self._lock:
            return {
                "vector_store": self.name,
                "collections": {name: len(recs) for name, recs in self._records.items()},
            }


def _normalise(matrix: np.ndarray) -> np.ndarray:
    if matrix.size == 0:
        return matrix
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms
