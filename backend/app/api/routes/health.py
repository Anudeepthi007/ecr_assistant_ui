"""Health and platform introspection endpoints."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.config import settings
from app.database import engine
from app.dependencies import DbSession
from app.integrations.providers import source_systems
from app.data.csv_store import current_counts
from app.llm.provider import get_llm
from app.services.code_analysis_service import get_code_analysis_service
from app.services.rag_service import get_rag_service

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, Any]:
    """Liveness plus a truthful picture of which subsystems are degraded."""
    from sqlalchemy import text

    database_ok = True
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        database_ok = False

    llm = get_llm().health()
    return {
        "status": "ok" if database_ok else "degraded",
        "app": settings.app_name,
        "version": settings.app_version,
        "environment": settings.app_env,
        "database": {
            "ok": database_ok,
            "source": "csv",
            "data_dir": settings.data_dir,
            "working_copy": engine.dialect.name,
        },
        "llm": llm,
        "demo_mode": bool(llm.get("mock")),
        "vector_store": get_rag_service().health(),
        "code_analysis": get_code_analysis_service().stats(),
        "source_systems": source_systems(),
    }


@router.get("/health/data")
def data_health(db: DbSession) -> dict[str, Any]:
    """Row counts of the data loaded from the CSV files."""
    return current_counts(db)
