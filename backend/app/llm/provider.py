"""Provider factory, startup probe and circuit breaker.

Two failure modes are handled explicitly because they are common in enterprise
networks: (a) no credentials at all, (b) credentials present but the provider
endpoint is unreachable (proxy / TLS interception / quota). In both cases the
platform must keep working, so the runtime degrades to :class:`MockProvider`.
"""
from __future__ import annotations

import threading
import time
from functools import lru_cache
from typing import Any, TypeVar

from pydantic import BaseModel

from app.config import settings
from app.llm.base import BaseLLMProvider
from app.llm.mock_provider import MockProvider
from app.logging import get_logger

logger = get_logger("ecr.llm")

T = TypeVar("T", bound=BaseModel)


def build_provider(name: str | None = None) -> BaseLLMProvider:
    """Instantiate a raw provider, degrading to :class:`MockProvider`."""
    resolved = name or settings.resolved_llm_provider()
    try:
        if resolved == "openai":
            from app.llm.openai_provider import OpenAIProvider

            return OpenAIProvider()
        if resolved == "azure_openai":
            from app.llm.openai_provider import OpenAIProvider

            return OpenAIProvider(azure=True)
        if resolved == "anthropic":
            from app.llm.anthropic_provider import AnthropicProvider

            return AnthropicProvider()
    except Exception as exc:
        logger.warning("llm.provider_fallback", requested=resolved, error=str(exc))
    return MockProvider()


class ResilientProvider(BaseLLMProvider):
    """Wraps a remote provider with a probe and a circuit breaker.

    After ``max_failures`` consecutive remote errors the breaker opens and every
    later call is served by the mock provider, so a dead endpoint can never
    stall an agent workflow.
    """

    def __init__(
        self, primary: BaseLLMProvider, max_failures: int = 3, cooldown_seconds: float = 120.0
    ) -> None:
        self._primary = primary
        self._mock = MockProvider()
        self._max_failures = max_failures
        self._cooldown = cooldown_seconds
        self._failures = 0
        self._opened_at = 0.0
        self._open = False
        self._lock = threading.Lock()
        self._probe_result: dict[str, Any] = {"probed": False}
        self.name = primary.name
        self.is_mock = primary.is_mock
        self.supports_remote_embeddings = primary.supports_remote_embeddings

    # -- breaker ----------------------------------------------------------
    @property
    def is_open(self) -> bool:
        """Open, unless the cooldown has elapsed - then try the primary again.

        Rate limits and gateway blips are transient, so a permanently open
        breaker would strand the platform in demo mode for the rest of the
        process lifetime.
        """
        if not self._open:
            return False
        if self._cooldown and (time.monotonic() - self._opened_at) >= self._cooldown:
            logger.info("llm.circuit_half_open", provider=self._primary.name)
            self._open = False
            self._failures = 0
            self.is_mock = self._primary.is_mock
            return False
        return True

    @property
    def active(self) -> BaseLLMProvider:
        return self._mock if self.is_open else self._primary

    def _record_failure(self, exc: Exception) -> None:
        with self._lock:
            self._failures += 1
            if self._failures >= self._max_failures and not self._open:
                self._open = True
                self._opened_at = time.monotonic()
                self.is_mock = True
                logger.warning(
                    "llm.circuit_open",
                    provider=self._primary.name,
                    failures=self._failures,
                    error=str(exc),
                )

    def _record_success(self) -> None:
        with self._lock:
            self._failures = 0

    def probe(self) -> dict[str, Any]:
        """One cheap call verifying the endpoint really answers."""
        if self._primary.is_mock:
            self._probe_result = {"probed": True, "reachable": True, "mock": True}
            return self._probe_result
        try:
            text = self._primary.generate(
                "Reply with the single word: READY", max_tokens=8, temperature=0.0
            )
            self._probe_result = {"probed": True, "reachable": True, "sample": text[:40]}
            logger.info("llm.probe_ok", provider=self._primary.name)
        except Exception as exc:
            if getattr(exc, "status_code", None) == 429:
                # The endpoint answered - it is only throttling this key. Stay on the
                # real model; the per-call retries absorb short rate-limit windows.
                self._probe_result = {"probed": True, "reachable": True, "rate_limited": True}
                logger.warning("llm.probe_rate_limited", provider=self._primary.name)
                return self._probe_result
            self._open = True
            self._opened_at = time.monotonic()
            self.is_mock = True
            self._probe_result = {"probed": True, "reachable": False, "error": str(exc)[:300]}
            logger.warning("llm.probe_failed", provider=self._primary.name, error=str(exc)[:300])
        return self._probe_result

    # -- interface --------------------------------------------------------
    def generate(self, prompt: str, *, fallback: str | None = None, **kwargs: Any) -> str:
        """Generate text, degrading to ``fallback`` when the endpoint is unavailable.

        Callers that show the text to a user must pass their grounded baseline as
        ``fallback``: the mock provider echoes the prompt, which must never reach
        the page.
        """
        if self.is_open:
            return fallback if fallback is not None else self._mock.generate(prompt, **kwargs)
        try:
            result = self._primary.generate(prompt, **kwargs)
            self._record_success()
            return result
        except Exception as exc:
            self._record_failure(exc)
            return fallback if fallback is not None else self._mock.generate(prompt, **kwargs)

    def generate_structured(self, prompt: str, schema: type[T], **kwargs: Any) -> T:
        if self.is_open:
            return self._mock.generate_structured(prompt, schema, **kwargs)
        try:
            result = self._primary.generate_structured(prompt, schema, **kwargs)
            self._record_success()
            return result
        except Exception as exc:
            self._record_failure(exc)
            return self._mock.generate_structured(prompt, schema, **kwargs)

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self.embed_with_mode(texts)[0]

    def embed_with_mode(self, texts: list[str]) -> tuple[list[list[float]], str]:
        """Embed and report which embedder produced the vectors.

        Vectors from two different embedders are not comparable, so the RAG
        layer needs to know when a fallback happened in order to re-index.
        """
        if self.is_open or not self._primary.supports_remote_embeddings:
            return self._mock.embed(texts), "local"
        try:
            result = self._primary.embed(texts)
            self._record_success()
            return result, "remote"
        except Exception as exc:
            self._record_failure(exc)
            logger.warning("llm.embed_fallback", provider=self._primary.name, error=str(exc)[:200])
            return self._mock.embed(texts), "local"

    def narrate(self, **kwargs: Any) -> str:
        if self.is_open:
            return self._mock.narrate(**kwargs)
        try:
            return self._primary.narrate(**kwargs)
        except Exception as exc:  # pragma: no cover - narrate already guards
            self._record_failure(exc)
            return self._mock.narrate(**kwargs)

    def health(self) -> dict[str, Any]:
        return {
            "provider": self._primary.name,
            "configured_provider": settings.llm_provider,
            "effective_provider": "mock" if self.is_open else self._primary.name,
            "mock": self.is_mock,
            "circuit_open": self.is_open,
            "cooldown_seconds": self._cooldown,
            "consecutive_failures": self._failures,
            "probe": self._probe_result,
            "available": True,
        }


@lru_cache
def get_llm() -> ResilientProvider:
    provider = ResilientProvider(build_provider())
    logger.info(
        "llm.provider_selected", provider=provider.name, mock=provider.is_mock
    )
    return provider
