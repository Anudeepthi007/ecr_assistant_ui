"""Retrieval Augmented Generation layer.

Indexes requirements, defects, test cases and ECR descriptions, then serves
hybrid retrieval (dense vector similarity + lexical keyword overlap) to the
agents. Hybrid scoring matters here: enterprise artifacts are short and full of
identifiers, where pure dense retrieval alone is brittle.

Embeddings are cached in a file next to the data (not in the CSVs), keyed by a
hash of each document's text. A restart reuses them, and editing a CSV row only
re-embeds the rows whose text changed.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

from sqlalchemy.orm import Session

from app.config import settings
from app.llm.base import hashed_embedding, tokenize
from app.llm.provider import get_llm
from app.logging import get_logger
from app.models import Defect, ECR, Requirement, TestCase
from app.vectorstore import (
    COLLECTION_DEFECTS,
    COLLECTION_ECRS,
    COLLECTION_REQUIREMENTS,
    COLLECTION_TESTS,
    VectorRecord,
    get_vector_store,
)

logger = get_logger("ecr.rag")


@dataclass(slots=True)
class RetrievedDocument:
    id: str
    text: str
    metadata: dict[str, Any]
    dense_score: float
    lexical_score: float
    hybrid_score: float

    @property
    def relevance(self) -> float:
        """Hybrid score mapped onto a 0-100 relevance percentage."""
        return round(max(0.0, min(1.0, self.hybrid_score)) * 100, 1)


def _digest(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


class RAGService:
    """Owns the embedding index lifecycle and hybrid retrieval."""

    DENSE_WEIGHT = 0.65
    LEXICAL_WEIGHT = 0.35

    def __init__(self) -> None:
        self._store = get_vector_store()
        self._llm = get_llm()
        self._lock = threading.RLock()
        self._indexed = False
        # Vectors from different embedders are not comparable. The index records
        # which embedder built it so a mid-flight fallback triggers a rebuild.
        self._index_mode: str | None = None
        self._embed_mode: str = "unknown"
        self._pinned_mode: str | None = None
        self._embed_mode_changed = False
        self._vectors: dict[str, dict[str, dict[str, Any]]] = {}
        # query text -> (embedder mode, vector); repeat analyses skip the remote call
        self._query_cache: OrderedDict[str, tuple[str, list[float]]] = OrderedDict()

    # -- document text builders -------------------------------------------
    @staticmethod
    def _requirement_text(r: Requirement) -> str:
        return (
            f"{r.requirement_id} {r.title}. {r.description} "
            f"domain={r.business_domain} component={r.component} "
            f"features={' '.join(r.features or [])}"
        )

    @staticmethod
    def _defect_text(d: Defect) -> str:
        return (
            f"{d.defect_id} {d.title}. {d.description} root_cause={d.root_cause} "
            f"category={d.root_cause_category} component={d.affected_component} "
            f"severity={d.severity}"
        )

    @staticmethod
    def _test_text(t: TestCase) -> str:
        return (
            f"{t.test_case_id} {t.title}. {t.description} feature={t.feature} "
            f"folder={t.folder} component={t.component} requirement={t.requirement_id} "
            f"type={t.test_polarity} technique={t.test_technique} "
            f"tags={' '.join(t.tags or [])}"
        )

    @staticmethod
    def _ecr_text(e: ECR) -> str:
        return f"{e.ecr_id} {e.title}. {e.description}"

    def _specs(self):
        return [
            (COLLECTION_REQUIREMENTS, Requirement, "requirement_id", self._requirement_text),
            (COLLECTION_DEFECTS, Defect, "defect_id", self._defect_text),
            (COLLECTION_TESTS, TestCase, "test_case_id", self._test_text),
            (COLLECTION_ECRS, ECR, "ecr_id", self._ecr_text),
        ]

    # -- indexing ---------------------------------------------------------
    def index_all(self, db: Session, *, force: bool = False) -> dict[str, int]:
        """Build every collection, reusing cached embeddings whose text is unchanged."""
        with self._lock:
            if self._indexed and not force:
                return {name: self._store.count(name) for name, *_ in self._specs()}
            cache_mode, cache = (None, {}) if force else self._read_cache()
            self._pinned_mode = "local" if cache_mode == "local" else None
            self._embed_mode = cache_mode or "unknown"
            self._embed_mode_changed = False

            counts = self._build(db, cache)
            # Cached vectors and freshly embedded ones must come from the same
            # embedder; if they do not (or the embedder fell back mid-way), rebuild.
            mismatch = cache_mode is not None and self._embed_mode not in (cache_mode, "unknown")
            if mismatch or (self._pinned_mode == "local" and self._embed_mode_changed):
                logger.warning("rag.reindexing", cache_mode=cache_mode, current=self._embed_mode)
                self._embed_mode_changed = False
                counts = self._build(db, {})

            self._indexed = True
            self._index_mode = self._embed_mode
            self._write_cache()
            logger.info("rag.indexed", mode=self._index_mode, **counts)
            return counts

    def _build(self, db: Session, cache: dict[str, dict[str, dict[str, Any]]]) -> dict[str, int]:
        counts: dict[str, int] = {}
        vectors_out: dict[str, dict[str, dict[str, Any]]] = {}
        reused = embedded = 0
        for collection, model, key, text_fn in self._specs():
            rows = db.query(model).all()
            ids = [getattr(row, key) for row in rows]
            texts = [text_fn(row) for row in rows]
            hashes = [_digest(text) for text in texts]
            cached = cache.get(collection, {})
            vectors: list[list[float] | None] = [None] * len(rows)
            missing: list[int] = []
            for index, (doc_id, digest) in enumerate(zip(ids, hashes)):
                entry = cached.get(doc_id)
                if entry and entry.get("h") == digest and len(entry.get("v") or []) == settings.embedding_dim:
                    vectors[index] = entry["v"]
                else:
                    missing.append(index)
            if missing:
                fresh = self._embed([texts[index] for index in missing])
                for index, vector in zip(missing, fresh):
                    vectors[index] = vector
            reused += len(rows) - len(missing)
            embedded += len(missing)
            try:
                self._store.reset(collection)  # rows removed from a CSV must disappear
            except NotImplementedError:  # pragma: no cover
                pass
            records = [
                VectorRecord(id=ids[i], text=texts[i], vector=vectors[i], metadata=rows[i].as_dict())
                for i in range(len(rows))
            ]
            counts[collection] = self._store.upsert(collection, records)
            vectors_out[collection] = {ids[i]: {"h": hashes[i], "v": vectors[i]} for i in range(len(rows))}
        self._vectors = vectors_out
        logger.info("rag.embeddings", reused=reused, embedded=embedded)
        return counts

    def index_ecr(self, ecr: ECR) -> None:
        """Index a single (newly created) ECR without a full rebuild."""
        text = self._ecr_text(ecr)
        vector = self._embed([text])[0]
        self._store.upsert(
            COLLECTION_ECRS, [VectorRecord(id=ecr.ecr_id, text=text, vector=vector, metadata=ecr.as_dict())]
        )
        self._vectors.setdefault(COLLECTION_ECRS, {})[ecr.ecr_id] = {"h": _digest(text), "v": vector}
        self._write_cache()

    def _embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed, pinning the mode for the whole process once it degrades."""
        if not texts:
            return []
        if self._pinned_mode == "local":
            self._embed_mode = "local"
            return [hashed_embedding(text) for text in texts]
        vectors, mode = self._llm.embed_with_mode(list(texts))
        if mode == "local" and self._embed_mode == "remote":
            self._embed_mode_changed = True
        if mode == "local":
            self._pinned_mode = "local"
        self._embed_mode = mode
        return vectors

    # -- embedding cache file ----------------------------------------------
    @staticmethod
    def _cache_path() -> Path:
        return Path(settings.embedding_cache_path)

    def _remote_embeddings_available(self) -> bool:
        if not self._llm.supports_remote_embeddings:
            return False
        return not getattr(self._llm, "is_open", False)

    def _read_cache(self) -> tuple[str | None, dict[str, dict[str, dict[str, Any]]]]:
        path = self._cache_path()
        if not path.exists():
            return None, {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None, {}
        mode = payload.get("mode")
        if payload.get("dim") != settings.embedding_dim or mode not in ("remote", "local"):
            return None, {}
        if mode == "remote" and (
            not self._remote_embeddings_available()
            or payload.get("model") != settings.openai_embedding_model
        ):
            return None, {}
        if mode == "local" and self._remote_embeddings_available():
            logger.info("rag.cache_stale_local_index")  # better vectors are available now
            return None, {}
        return mode, payload.get("collections") or {}

    def _write_cache(self) -> None:
        # Only remote vectors are worth keeping: local ones take well under a second
        # to recompute, and writing them would throw away a remote cache that cost
        # minutes of gateway quota whenever the gateway is briefly unreachable.
        if self._embed_mode != "remote":
            return
        payload = {
            "mode": self._embed_mode,
            "model": settings.openai_embedding_model if self._embed_mode == "remote" else "hashed",
            "dim": settings.embedding_dim,
            "collections": self._vectors,
        }
        path = self._cache_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
            os.replace(tmp, path)
        except OSError as exc:  # pragma: no cover - cache is best effort
            logger.warning("rag.cache_write_failed", error=str(exc))

    def _ensure_index_consistency(self) -> None:
        """Rebuild the index if the embedder changed under us (remote -> local)."""
        if not self._indexed or self._index_mode is None or self._embed_mode == "unknown":
            return
        if self._embed_mode == self._index_mode:
            return
        logger.warning("rag.embedder_changed", index_mode=self._index_mode, current=self._embed_mode)
        from app.database import session_scope

        with session_scope() as db:
            self._indexed = False
            self.index_all(db, force=True)

    # -- retrieval --------------------------------------------------------
    def retrieve(
        self,
        collection: str,
        query: str,
        *,
        k: int = 10,
        keywords: Iterable[str] | None = None,
        where: dict[str, Any] | None = None,
        min_relevance: float = 0.0,
    ) -> list[RetrievedDocument]:
        """Hybrid search: dense cosine similarity blended with keyword overlap."""
        if not query.strip():
            return []
        query_vector = self._query_vector(query)
        self._ensure_index_consistency()
        # over-fetch, then re-rank with the lexical signal
        hits = self._store.search(collection, query_vector, k=max(k * 4, 20), where=where)
        query_tokens = set(tokenize(query)) | {kw.lower() for kw in (keywords or [])}
        documents: list[RetrievedDocument] = []
        for hit in hits:
            doc_tokens = set(tokenize(hit.text))
            overlap = len(query_tokens & doc_tokens)
            lexical = overlap / max(len(query_tokens), 1)
            dense = max(0.0, hit.score)
            hybrid = self.DENSE_WEIGHT * dense + self.LEXICAL_WEIGHT * min(1.0, lexical * 1.6)
            if hybrid * 100 < min_relevance:
                continue
            documents.append(
                RetrievedDocument(
                    id=hit.id,
                    text=hit.text,
                    metadata=hit.metadata,
                    dense_score=round(dense, 4),
                    lexical_score=round(lexical, 4),
                    hybrid_score=round(hybrid, 4),
                )
            )
        documents.sort(key=lambda doc: doc.hybrid_score, reverse=True)
        return documents[:k]

    QUERY_CACHE_SIZE = 512

    def _query_vector(self, query: str) -> list[float]:
        """Embed a query once; reuse it while the index is built by the same embedder."""
        with self._lock:
            cached = self._query_cache.get(query)
            if cached and cached[0] == (self._index_mode or self._embed_mode):
                self._query_cache.move_to_end(query)
                return cached[1]
        vector = self._embed([query])[0]
        with self._lock:
            self._query_cache[query] = (self._embed_mode, vector)
            while len(self._query_cache) > self.QUERY_CACHE_SIZE:
                self._query_cache.popitem(last=False)
        return vector

    def health(self) -> dict[str, Any]:
        return {
            "indexed": self._indexed,
            "store": self._store.health(),
            "embedding_mode": self._embed_mode,
            "index_mode": self._index_mode,
            "embedding_cache": str(self._cache_path()),
            "embedding_provider": "remote" if self._llm.supports_remote_embeddings else "local-hashed",
        }


_rag_service: RAGService | None = None
_rag_lock = threading.Lock()


def get_rag_service() -> RAGService:
    global _rag_service
    with _rag_lock:
        if _rag_service is None:
            _rag_service = RAGService()
        return _rag_service
