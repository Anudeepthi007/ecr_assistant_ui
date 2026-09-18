"""Vector store factory.

Collection names are shared constants so the RAG service, the seeder and the
agents all address the same indexes.
"""
from __future__ import annotations

from functools import lru_cache

from app.config import settings
from app.logging import get_logger
from app.vectorstore.base import SearchHit, VectorRecord, VectorStore
from app.vectorstore.memory_store import InMemoryVectorStore

logger = get_logger("ecr.vectorstore")

COLLECTION_REQUIREMENTS = "requirements"
COLLECTION_DEFECTS = "defects"
COLLECTION_TESTS = "test_cases"
COLLECTION_ECRS = "ecrs"
ALL_COLLECTIONS = (
    COLLECTION_REQUIREMENTS,
    COLLECTION_DEFECTS,
    COLLECTION_TESTS,
    COLLECTION_ECRS,
)


def build_vector_store(kind: str | None = None) -> VectorStore:
    resolved = kind or settings.vector_store
    try:
        if resolved == "pgvector":
            from app.vectorstore.pgvector_store import PgVectorStore

            return PgVectorStore()
        if resolved == "chroma":
            from app.vectorstore.chroma_store import ChromaVectorStore

            return ChromaVectorStore()
    except Exception as exc:
        logger.warning("vectorstore.fallback", requested=resolved, error=str(exc))
    return InMemoryVectorStore()


@lru_cache
def get_vector_store() -> VectorStore:
    store = build_vector_store()
    logger.info("vectorstore.selected", store=store.name)
    return store


__all__ = [
    "ALL_COLLECTIONS",
    "COLLECTION_DEFECTS",
    "COLLECTION_ECRS",
    "COLLECTION_REQUIREMENTS",
    "COLLECTION_TESTS",
    "SearchHit",
    "VectorRecord",
    "VectorStore",
    "build_vector_store",
    "get_vector_store",
]
