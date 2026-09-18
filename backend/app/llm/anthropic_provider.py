"""Anthropic provider (Messages API over plain HTTP)."""
from __future__ import annotations

import json
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel

from app.config import settings
from app.llm.base import BaseLLMProvider, LLMError, hashed_embedding
from app.llm.openai_provider import _extract_json
from app.logging import get_logger

logger = get_logger("ecr.llm.anthropic")

T = TypeVar("T", bound=BaseModel)


class AnthropicProvider(BaseLLMProvider):
    name = "anthropic"
    supports_remote_embeddings = False  # embeddings stay local (hashed vectors)

    def __init__(self) -> None:
        self.api_key = settings.anthropic_api_key or ""
        self.endpoint = settings.anthropic_base_url.rstrip("/")
        self.model = settings.anthropic_model
        if not self.api_key:
            raise LLMError("Anthropic provider selected but no API key is configured")

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = httpx.post(
                f"{self.endpoint}/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json=payload,
                timeout=settings.llm_timeout_seconds,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as exc:
            raise LLMError(f"Anthropic request failed: {exc}") from exc

    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int | None = None,
        temperature: float = 0.2,
        fast: bool = False,
    ) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens or settings.llm_max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            payload["system"] = system
        data = self._post(payload)
        blocks = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
        return "".join(blocks)

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
        instruction = (
            f"{prompt}\n\nRespond with a single JSON object (no prose, no code fence) "
            f"matching this schema:\n{json.dumps(schema.model_json_schema())[:4000]}"
        )
        try:
            raw = self.generate(instruction, system=system, temperature=temperature, fast=fast)
            return schema.model_validate(_extract_json(raw))
        except Exception as exc:
            logger.warning("llm.structured_failed", provider=self.name, error=str(exc))
            return schema.model_validate(fallback or {})

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [hashed_embedding(text) for text in texts]
