"""Structured logging for the platform.

Uses ``structlog`` when available and degrades to the stdlib logger otherwise.
Secrets are never logged: :func:`redact` scrubs anything that looks like a key.
"""
from __future__ import annotations

import logging
import sys
from typing import Any, Mapping

from app.config import settings

_SENSITIVE_HINTS = ("key", "token", "secret", "password", "authorization")


def redact(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return ``payload`` with sensitive looking values masked."""
    clean: dict[str, Any] = {}
    for key, value in payload.items():
        if any(hint in key.lower() for hint in _SENSITIVE_HINTS):
            clean[key] = "***redacted***"
        elif isinstance(value, Mapping):
            clean[key] = redact(value)
        else:
            clean[key] = value
    return clean


def configure_logging() -> None:
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        stream=sys.stdout,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    )
    logging.getLogger("uvicorn.access").setLevel(max(level, logging.INFO))
    try:  # pragma: no cover - structlog is optional
        import structlog

        structlog.configure(
            processors=[
                structlog.contextvars.merge_contextvars,
                structlog.processors.add_log_level,
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.dev.ConsoleRenderer(colors=False),
            ],
            wrapper_class=structlog.make_filtering_bound_logger(level),
            cache_logger_on_first_use=True,
        )
    except Exception:  # pragma: no cover
        pass


class _StdlibAdapter:
    """Minimal key/value logger used when structlog is unavailable."""

    def __init__(self, name: str) -> None:
        self._log = logging.getLogger(name)

    def _emit(self, level: int, event: str, **kw: Any) -> None:
        if kw:
            extras = " ".join(f"{k}={v}" for k, v in redact(kw).items())
            self._log.log(level, "%s | %s", event, extras)
        else:
            self._log.log(level, event)

    def debug(self, event: str, **kw: Any) -> None:
        self._emit(logging.DEBUG, event, **kw)

    def info(self, event: str, **kw: Any) -> None:
        self._emit(logging.INFO, event, **kw)

    def warning(self, event: str, **kw: Any) -> None:
        self._emit(logging.WARNING, event, **kw)

    def error(self, event: str, **kw: Any) -> None:
        self._emit(logging.ERROR, event, **kw)

    def exception(self, event: str, **kw: Any) -> None:
        self._log.exception(event, extra=redact(kw) or None)


def get_logger(name: str = "ecr") -> Any:
    try:  # pragma: no cover - structlog is optional
        import structlog

        return structlog.get_logger(name)
    except Exception:  # pragma: no cover
        return _StdlibAdapter(name)
