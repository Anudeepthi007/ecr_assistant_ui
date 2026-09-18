"""LLM provider abstraction.

Every agent talks to the model through this interface only, which is what makes
the platform runnable with *no* API key at all (see :mod:`app.llm.mock_provider`).

Design rule enforced across the codebase:
    deterministic engines compute the numbers, the LLM only explains them.
Hence :meth:`narrate` always receives a ``fallback`` narrative produced by the
deterministic layer, and any provider failure degrades to that fallback.
"""
from __future__ import annotations

import hashlib
import math
import re
from abc import ABC, abstractmethod
from typing import Any, TypeVar

from pydantic import BaseModel

from app.config import settings
from app.logging import get_logger
from app.prompts import NARRATION_SYSTEM_PROMPT, NARRATION_TASK

logger = get_logger("ecr.llm")

T = TypeVar("T", bound=BaseModel)

_TOKEN_RE = re.compile(r"[a-z0-9_]+")
_STOPWORDS = {
    "the", "a", "an", "and", "or", "to", "of", "for", "in", "on", "with", "is",
    "are", "be", "should", "must", "that", "this", "it", "as", "by", "from",
    "when", "will", "shall", "at", "we", "if", "not", "no", "than", "then",
}


def tokenize(text: str) -> list[str]:
    """Lower-cased, stop-word filtered tokens (also used by the vector store)."""
    return [t for t in _TOKEN_RE.findall((text or "").lower()) if t not in _STOPWORDS and len(t) > 2]


def hashed_embedding(text: str, dim: int | None = None) -> list[float]:
    """Deterministic hashing-trick embedding.

    Behaves like an L2-normalised sparse lexical vector: cosine similarity
    approximates weighted token overlap, which gives the PoC meaningful
    "semantic" search with zero external calls and zero model download.
    """
    dim = dim or settings.embedding_dim
    vector = [0.0] * dim
    tokens = tokenize(text)
    if not tokens:
        return vector
    counts: dict[str, int] = {}
    for token in tokens:
        counts[token] = counts.get(token, 0) + 1
    for token, count in counts.items():
        digest = hashlib.md5(token.encode("utf-8")).digest()
        idx = int.from_bytes(digest[:4], "big") % dim
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        # sub-linear term weighting keeps long documents from dominating
        vector[idx] += sign * (1.0 + math.log(count))
        # a second bucket reduces hash collisions
        idx2 = int.from_bytes(digest[5:9], "big") % dim
        vector[idx2] += sign * 0.5
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [v / norm for v in vector]


class LLMError(RuntimeError):
    """Raised when a remote provider cannot fulfil a request."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code  # HTTP status from the endpoint, if any


class BaseLLMProvider(ABC):
    """Contract implemented by every provider."""

    name: str = "base"
    is_mock: bool = False
    supports_remote_embeddings: bool = False

    @abstractmethod
    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int | None = None,
        temperature: float = 0.2,
        fast: bool = False,
    ) -> str:
        """Free-form completion. ``fast`` selects the cheap narration model."""

    @abstractmethod
    def generate_structured(
        self,
        prompt: str,
        schema: type[T],
        *,
        system: str | None = None,
        fallback: dict[str, Any] | None = None,
        temperature: float = 0.0,
        fast: bool = True,
    ) -> T:
        """Validated structured completion (always returns a valid ``schema``).

        ``fast`` selects the cheap model; pass ``False`` for text a user reads first.
        """

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed documents. Providers without an embedding API use the local one."""
        return [hashed_embedding(text) for text in texts]

    def narrate(
        self,
        *,
        task: str,
        context: dict[str, Any],
        fallback: str,
        system: str | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """Explain a deterministic result in prose.

        ``fallback`` is the deterministic narrative; it is returned verbatim by
        the mock provider, whenever a remote call fails, and unless
        ``LLM_NARRATION`` is on (each narration is a full LLM round trip, and a
        user is waiting on the analysis).
        """
        if self.is_mock or not settings.llm_narration:
            return fallback
        try:
            prompt = _build_narration_prompt(task, context, fallback)
            text = self.generate(
                prompt,
                system=system or NARRATION_SYSTEM_PROMPT,
                max_tokens=max_tokens or settings.narration_max_tokens,
                temperature=0.2,
                fast=True,
            )
            return text.strip() or fallback
        except Exception as exc:  # graceful degradation - never break a workflow
            logger.warning("llm.narrate_failed", provider=self.name, error=str(exc))
            return fallback

    def health(self) -> dict[str, Any]:
        return {"provider": self.name, "mock": self.is_mock, "available": True}


def _build_narration_prompt(task: str, context: dict[str, Any], fallback: str) -> str:
    import json

    return NARRATION_TASK.format(
        task=task,
        context=json.dumps(context, indent=2, default=str)[:6000],
        fallback=fallback,
    )
