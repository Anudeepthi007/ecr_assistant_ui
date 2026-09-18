"""Vector store abstraction used by the RAG layer."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass(slots=True)
class VectorRecord:
    id: str
    text: str
    vector: list[float]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SearchHit:
    id: str
    score: float
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


class VectorStore(ABC):
    """Minimal contract: upsert documents, search by vector, inspect size."""

    name: str = "base"

    @abstractmethod
    def upsert(self, collection: str, records: Iterable[VectorRecord]) -> int: ...

    @abstractmethod
    def search(
        self,
        collection: str,
        query_vector: list[float],
        *,
        k: int = 10,
        min_score: float = 0.0,
        where: dict[str, Any] | None = None,
    ) -> list[SearchHit]: ...

    @abstractmethod
    def count(self, collection: str) -> int: ...

    def reset(self, collection: str | None = None) -> None:  # pragma: no cover
        raise NotImplementedError

    def health(self) -> dict[str, Any]:
        return {"vector_store": self.name}
