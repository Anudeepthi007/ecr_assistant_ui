"""A throttled gateway (HTTP 429) must be retried, not treated as a dead endpoint."""
from __future__ import annotations

import httpx
import pytest

from app.llm import openai_provider
from app.llm.base import LLMError
from app.llm.openai_provider import OpenAIProvider
from app.llm.provider import ResilientProvider


def _response(status: int, body: dict | None = None, headers: dict | None = None) -> httpx.Response:
    request = httpx.Request("POST", "https://gateway.test/v1/chat/completions")
    return httpx.Response(status, json=body or {}, headers=headers or {}, request=request)


OK = {"choices": [{"message": {"content": "READY"}}]}


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setattr(openai_provider.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(openai_provider.settings, "openai_api_key", "test-key")
    monkeypatch.setattr(openai_provider.settings, "openai_base_url", "https://gateway.test/v1")
    return OpenAIProvider()


def test_429_is_retried_until_the_gateway_answers(provider, monkeypatch):
    replies = [_response(429, headers={"retry-after": "2"}), _response(429), _response(200, OK)]
    monkeypatch.setattr(openai_provider.httpx, "post", lambda *a, **k: replies.pop(0))
    assert provider.generate("ping") == "READY"
    assert not replies


def test_client_errors_other_than_throttling_are_not_retried(provider, monkeypatch):
    calls = []

    def post(*_args, **_kwargs):
        calls.append(1)
        return _response(400)

    monkeypatch.setattr(openai_provider.httpx, "post", post)
    with pytest.raises(LLMError) as raised:
        provider.generate("ping")
    assert raised.value.status_code == 400
    assert len(calls) == 1


def test_rate_limited_probe_keeps_the_real_model_active(provider, monkeypatch):
    monkeypatch.setattr(openai_provider.httpx, "post", lambda *a, **k: _response(429))
    resilient = ResilientProvider(provider)
    result = resilient.probe()
    assert result["rate_limited"] is True
    assert not resilient.is_open
    assert resilient.active is provider


def test_a_refused_call_returns_the_callers_fallback_never_the_prompt(provider, monkeypatch):
    """Regression: a throttled answer call used to show the raw prompt on the page."""
    monkeypatch.setattr(openai_provider.httpx, "post", lambda *a, **k: _response(429))
    resilient = ResilientProvider(provider)
    assert resilient.generate("QUESTION: prompt text", fallback="baseline answer") == "baseline answer"
    for _ in range(3):
        resilient.generate("again", fallback="baseline answer")
    assert resilient.is_open
    assert resilient.generate("QUESTION: prompt text", fallback="baseline answer") == "baseline answer"


def test_a_timeout_is_not_retried_because_the_gateway_may_have_billed_it(provider, monkeypatch):
    calls = []

    def post(*_args, **_kwargs):
        calls.append(1)
        raise httpx.ReadTimeout("timed out")

    monkeypatch.setattr(openai_provider.httpx, "post", post)
    with pytest.raises(LLMError):
        provider.generate("ping")
    assert len(calls) == 1
