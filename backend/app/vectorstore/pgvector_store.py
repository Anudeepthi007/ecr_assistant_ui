"""PostgreSQL + pgvector backed store.

Used automatically when ``VECTOR_STORE=pgvector`` and the database is
PostgreSQL with the ``vector`` extension available. Falls back to the in-memory
store at construction time when either precondition is missing, so the same
code path works on a laptop and in docker-compose.
"""
from __future__ import annotations

from typing import Any, Iterable

from sqlalchemy import text

from app.config import settings
from app.database import engine
from app.logging import get_logger
from app.vectorstore.base import SearchHit, VectorRecord, VectorStore

logger = get_logger("ecr.vectorstore.pgvector")

_TABLE = "vector_documents"


class PgVectorStore(VectorStore):
    name = "pgvector"

    def __init__(self) -> None:
        if settings.is_sqlite:
            raise RuntimeError("pgvector requires a PostgreSQL DATABASE_URL")
        dim = settings.embedding_dim
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.execute(
                text(
                    f"""
                    CREATE TABLE IF NOT EXISTS {_TABLE} (
                        collection TEXT NOT NULL,
                        doc_id     TEXT NOT NULL,
                        content    TEXT NOT NULL,
                        metadata   JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                        embedding  vector({dim}),
                        PRIMARY KEY (collection, doc_id)
                    )
                    """
                )
            )
            conn.execute(
                text(
                    f"CREATE INDEX IF NOT EXISTS idx_{_TABLE}_collection "
                    f"ON {_TABLE} (collection)"
                )
            )
        logger.info("pgvector.ready", dim=dim)

    def upsert(self, collection: str, records: Iterable[VectorRecord]) -> int:
        import json

        items = list(records)
        if not items:
            return 0
        with engine.begin() as conn:
            for record in items:
                conn.execute(
                    text(
                        f"""
                        INSERT INTO {_TABLE} (collection, doc_id, content, metadata, embedding)
                        VALUES (:collection, :doc_id, :content, CAST(:metadata AS jsonb),
                                CAST(:embedding AS vector))
                        ON CONFLICT (collection, doc_id) DO UPDATE
                        SET content = EXCLUDED.content,
                            metadata = EXCLUDED.metadata,
                            embedding = EXCLUDED.embedding
                        """
                    ),
                    {
                        "collection": collection,
                        "doc_id": record.id,
                        "content": record.text,
                        "metadata": json.dumps(record.metadata),
                        "embedding": _to_vector_literal(record.vector),
                    },
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
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    f"""
                    SELECT doc_id, content, metadata,
                           1 - (embedding <=> CAST(:embedding AS vector)) AS score
                    FROM {_TABLE}
                    WHERE collection = :collection
                    ORDER BY embedding <=> CAST(:embedding AS vector)
                    LIMIT :limit
                    """
                ),
                {
                    "collection": collection,
                    "embedding": _to_vector_literal(query_vector),
                    "limit": max(k * 3, k),
                },
            ).mappings()
            hits: list[SearchHit] = []
            for row in rows:
                metadata = dict(row["metadata"] or {})
                score = float(row["score"])
                if score < min_score:
                    continue
                if where and any(metadata.get(key) != value for key, value in where.items()):
                    continue
                hits.append(
                    SearchHit(
                        id=row["doc_id"], score=score, text=row["content"], metadata=metadata
                    )
                )
                if len(hits) >= k:
                    break
            return hits

    def count(self, collection: str) -> int:
        with engine.connect() as conn:
            return int(
                conn.execute(
                    text(f"SELECT COUNT(*) FROM {_TABLE} WHERE collection = :c"),
                    {"c": collection},
                ).scalar()
                or 0
            )

    def reset(self, collection: str | None = None) -> None:
        with engine.begin() as conn:
            if collection is None:
                conn.execute(text(f"DELETE FROM {_TABLE}"))
            else:
                conn.execute(
                    text(f"DELETE FROM {_TABLE} WHERE collection = :c"), {"c": collection}
                )


def _to_vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{value:.6f}" for value in vector) + "]"
