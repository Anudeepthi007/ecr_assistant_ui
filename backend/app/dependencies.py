"""Shared FastAPI dependencies: auth, rate limiting placeholder, services."""
from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db

DbSession = Annotated[Session, Depends(get_db)]

_BUCKETS: dict[str, deque[float]] = defaultdict(deque)


async def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Optional API-key gate. Disabled unless ``API_KEY`` is configured."""
    if not settings.api_key:
        return
    if x_api_key != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or missing X-API-Key"
        )


async def rate_limit(request: Request) -> None:
    """In-process fixed-window limiter.

    A placeholder for a real gateway limiter: it is per-process and per-client
    IP, which is enough to protect a demo deployment. Disabled when
    ``RATE_LIMIT_PER_MINUTE`` is 0.
    """
    limit = settings.rate_limit_per_minute
    if not limit:
        return
    client = request.client.host if request.client else "unknown"
    now = time.time()
    bucket = _BUCKETS[client]
    while bucket and now - bucket[0] > 60:
        bucket.popleft()
    if len(bucket) >= limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="rate limit exceeded"
        )
    bucket.append(now)


CommonGuards = [Depends(require_api_key), Depends(rate_limit)]
