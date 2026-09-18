"""OpenAI / Azure OpenAI provider (plain HTTP, no vendor SDK required)."""
from __future__ import annotations

import json
import time
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel

from app.config import settings
from app.llm.base import BaseLLMProvider, LLMError, hashed_embedding
from app.logging import get_logger

logger = get_logger("ecr.llm.openai")

T = TypeVar("T", bound=BaseModel)


class OpenAIProvider(BaseLLMProvider):
    name = "openai"
    supports_remote_embeddings = True

    def __init__(self, *, azure: bool = False) -> None:
        self.azure = azure
        if azure:
            self.name = "azure_openai"
            self.api_key = settings.azure_openai_api_key or ""
            self.endpoint = (settings.azure_openai_endpoint or "").rstrip("/")
            self.model = settings.azure_openai_deployment
            self.supports_remote_embeddings = False
        else:
            self.api_key = settings.openai_api_key or ""
            self.endpoint = settings.openai_base_url.rstrip("/")
            self.model = settings.openai_model
            # Off by default: a remote embedding is a gateway request of its own.
            self.supports_remote_embeddings = settings.remote_embeddings
        self.fast_model = settings.openai_fast_model or ""
        if not self.api_key:
            raise LLMError("OpenAI provider selected but no API key is configured")

    # -- transport --------------------------------------------------------
    def _chat_url(self, model: str | None = None) -> str:
        if self.azure:
            return (
                f"{self.endpoint}/openai/deployments/{model or self.model}/chat/completions"
                f"?api-version={settings.azure_openai_api_version}"
            )
        return f"{self.endpoint}/chat/completions"

    def _headers(self) -> dict[str, str]:
        if self.azure:
            return {"api-key": self.api_key, "content-type": "application/json"}
        return {
            "authorization": f"Bearer {self.api_key}",
            "content-type": "application/json",
        }

    def _post(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST, retrying only requests the gateway did not process.

        A throttled (429) or never-connected request is retried with a short
        backoff, so a burst limit does not degrade the answer. Anything else -
        a timeout or a 5xx included - may already have been billed, so it fails
        once and the caller falls back to its rules. One agent call therefore
        never costs more than one processed request.
        """
        last_error: Exception | None = None
        status: int | None = None
        for attempt in range(settings.llm_max_retries + 1):
            try:
                response = httpx.post(
                    url,
                    headers=self._headers(),
                    json=payload,
                    timeout=settings.llm_timeout_seconds,
                )
                response.raise_for_status()
                return response.json()
            except httpx.HTTPError as exc:
                last_error = exc
                status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
                if not (status == 429 or isinstance(exc, httpx.ConnectError)):
                    break  # the gateway may have processed it: a retry would be a second request
                if attempt < settings.llm_max_retries:
                    time.sleep(self._retry_delay(exc, attempt))
        raise LLMError(f"OpenAI request failed: {last_error}", status_code=status) from last_error

    @staticmethod
    def _retry_delay(exc: httpx.HTTPError, attempt: int) -> float:
        """Honour the gateway's Retry-After on 429; otherwise back off exponentially."""
        if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429:
            header = exc.response.headers.get("retry-after", "")
            try:
                return min(max(float(header), 1.0), settings.llm_rate_limit_max_wait_seconds)
            except ValueError:
                return min(3.0 * (2**attempt), settings.llm_rate_limit_max_wait_seconds)
        return 0.8 * (2**attempt)

    # -- interface --------------------------------------------------------
    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int | None = None,
        temperature: float = 0.2,
        fast: bool = False,
    ) -> str:
        messages = ([{"role": "system", "content": system}] if system else []) + [
            {"role": "user", "content": prompt}
        ]
        model = self.fast_model if (fast and self.fast_model) else self.model
        data = self._post(
            self._chat_url(model),
            {
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens or settings.llm_max_tokens,
                "temperature": temperature,
            },
        )
        return data["choices"][0]["message"]["content"] or ""

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
            f"{prompt}\n\nRespond with a single JSON object matching this schema:\n"
            f"{json.dumps(schema.model_json_schema())[:4000]}"
        )
        try:
            raw = self.generate(
                instruction,
                system=system,
                temperature=temperature,
                max_tokens=settings.llm_max_tokens,
                fast=fast,
            )
            return schema.model_validate(_extract_json(raw))
        except Exception as exc:
            logger.warning("llm.structured_failed", provider=self.name, error=str(exc))
            return schema.model_validate(fallback or {})

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Batched embeddings. Raises on failure so callers can switch modes."""
        if not self.supports_remote_embeddings:
            return [hashed_embedding(text) for text in texts]
        batch = max(1, settings.embedding_batch_size)
        vectors: list[list[float]] = []
        for start in range(0, len(texts), batch):
            chunk = texts[start : start + batch]
            data = self._post(
                f"{self.endpoint}/embeddings",
                {"model": settings.openai_embedding_model, "input": chunk},
            )
            items = sorted(data["data"], key=lambda item: item.get("index", 0))
            vectors.extend(item["embedding"] for item in items)
        return vectors


def _extract_json(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        text = text.split("\n", 1)[1] if "\n" in text else text
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object found in model response")
    return json.loads(text[start : end + 1])
