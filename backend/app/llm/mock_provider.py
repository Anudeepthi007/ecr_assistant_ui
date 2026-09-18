"""Zero-dependency provider used when no LLM credentials are configured.

It is not a stub: agent intelligence in mock mode comes from the deterministic
rule engines (selection algorithm, dependency traversal, hashed
embeddings). This provider supplies the *language* layer around them.
"""
from __future__ import annotations

from typing import Any, TypeVar

from pydantic import BaseModel

from app.llm.base import BaseLLMProvider, hashed_embedding

T = TypeVar("T", bound=BaseModel)


class MockProvider(BaseLLMProvider):
    name = "mock"
    is_mock = True

    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int | None = None,
        temperature: float = 0.2,
        fast: bool = False,
    ) -> str:
        """Echo the deterministic baseline embedded in the prompt, if present."""
        marker = "DETERMINISTIC BASELINE NARRATIVE:"
        if marker in prompt:
            return prompt.split(marker, 1)[1].split("\n\nRewrite")[0].strip()
        return prompt.strip()[: max_tokens or 800]

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
        return schema.model_validate(fallback or {})

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [hashed_embedding(text) for text in texts]

    def health(self) -> dict[str, Any]:
        return {
            "provider": self.name,
            "mock": True,
            "available": True,
            "note": "Rule-based reasoning with hashed local embeddings. "
            "Set OPENAI_API_KEY or ANTHROPIC_API_KEY to enable an LLM.",
        }
