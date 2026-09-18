"""FastAPI application entrypoint."""
from __future__ import annotations

import threading
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.requests import Request

from app.api.routes import agents, analysis, chat, ecr, health, reports
from app.config import settings
from app.data.csv_store import writer as csv_writer
from app.database import init_db, session_scope
from app.dependencies import rate_limit, require_api_key
from app.logging import configure_logging, get_logger
from app.services.rag_service import get_rag_service

configure_logging()
logger = get_logger("ecr.api")

DESCRIPTION = """
**ECR Intelligence Agent** - AI-powered Engineering Change Request analysis.

Give it an ECR number and exactly three agents do the manual work:

1. **Retrieval Agent** - pulls the ECR record, traced and semantically matched
   requirements, historical defects, code impact, dependency reach, review
   comments and evidence.
2. **Correlation Agent** - links every artefact to the ECR, works out which
   components are impacted and selects the regression tests that matter.
3. **Summarization Agent** - answers in plain language with citations and
   publishes the report.

Runs fully offline in demo mode when no LLM credentials are configured.
"""


def _warmup() -> None:
    """Index in the background so startup is never blocked.

    There is no LLM probe here: every gateway request counts against the quota,
    and each agent's call already falls back to its rules when the gateway is down.
    """
    try:
        with session_scope() as db:
            get_rag_service().index_all(db)
    except Exception as exc:  # pragma: no cover - warmup must never kill the app
        logger.warning("startup.warmup_failed", error=str(exc))


@asynccontextmanager
async def lifespan(app: FastAPI):
    counts = init_db()  # load backend/data/*.csv
    logger.info("startup.data_loaded", data_dir=settings.data_dir, **counts)
    threading.Thread(target=_warmup, name="warmup", daemon=True).start()
    logger.info("startup.complete", env=settings.app_env, provider=settings.resolved_llm_provider())
    yield
    csv_writer.flush()  # write any pending changes back to the CSV files
    logger.info("shutdown.complete")


app = FastAPI(
    title=settings.app_name,
    description=DESCRIPTION,
    version=settings.app_version,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

GUARDS = [Depends(require_api_key), Depends(rate_limit)]

app.include_router(health.router, prefix=settings.api_prefix)
app.include_router(ecr.router, prefix=settings.api_prefix, dependencies=GUARDS)
app.include_router(analysis.router, prefix=settings.api_prefix, dependencies=GUARDS)
app.include_router(analysis.workflow_router, prefix=settings.api_prefix, dependencies=GUARDS)
app.include_router(agents.router, prefix=settings.api_prefix, dependencies=GUARDS)
app.include_router(reports.router, prefix=settings.api_prefix, dependencies=GUARDS)
app.include_router(chat.router, prefix=settings.api_prefix, dependencies=GUARDS)


@app.get("/")
def root() -> dict[str, str]:
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "docs": "/docs",
        "health": f"{settings.api_prefix}/health",
    }


@app.exception_handler(Exception)
async def unhandled_exception(request: Request, exc: Exception) -> JSONResponse:  # pragma: no cover
    logger.exception("api.unhandled", path=str(request.url.path))
    return JSONResponse(
        status_code=500,
        content={"detail": "internal error", "path": str(request.url.path)},
    )
