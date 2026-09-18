"""ECR application service: creation, lookup and workflow launch."""
from __future__ import annotations

import re
import threading
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.agents.orchestrator import run_workflow
from app.agents.runtime import WorkflowRun, registry
from app.logging import get_logger
from app.models import ECR
from app.repositories import ECRRepository, ImpactReportRepository
from app.schemas.ecr import ECRCreate
from app.services.rag_service import get_rag_service

logger = get_logger("ecr.service")

ECR_ID_PATTERN = re.compile(r"^ECR-\d{4}-\d{1,6}$", re.IGNORECASE)


class ECRNotFound(LookupError):
    pass


def normalise_ecr_id(value: str) -> str:
    return (value or "").strip().upper()


def next_ecr_id(db: Session) -> str:
    year = datetime.now(timezone.utc).year
    prefix = f"ECR-{year}-"
    existing = [
        int(row.ecr_id.rsplit("-", 1)[-1])
        for row in ECRRepository(db).list()
        if row.ecr_id.startswith(prefix) and row.ecr_id.rsplit("-", 1)[-1].isdigit()
    ]
    return f"{prefix}{max(existing, default=0) + 1:03d}"


def create_ecr(db: Session, payload: ECRCreate) -> ECR:
    repository = ECRRepository(db)
    ecr_id = normalise_ecr_id(payload.ecr_id or "") or next_ecr_id(db)
    if repository.get(ecr_id):
        raise ValueError(f"{ecr_id} already exists")
    ecr = ECR(ecr_id=ecr_id, status="NEW", **payload.model_dump(exclude={"ecr_id"}))
    repository.add(ecr)
    try:
        get_rag_service().index_ecr(ecr)
        db.commit()
    except Exception as exc:  # pragma: no cover - indexing must not block creation
        logger.warning("ecr.index_failed", ecr_id=ecr_id, error=str(exc))
    logger.info("ecr.created", ecr_id=ecr_id)
    return ecr


def get_ecr(db: Session, ecr_id: str) -> ECR:
    ecr = ECRRepository(db).get(normalise_ecr_id(ecr_id))
    if ecr is None:
        raise ECRNotFound(ecr_id)
    return ecr


def start_analysis(
    db: Session, ecr_id: str, options: dict[str, Any], *, background: bool = True
) -> WorkflowRun:
    """Launch the agent workflow. Returns immediately when ``background``."""
    ecr = get_ecr(db, ecr_id)
    payload = ecr.as_dict()
    if options.get("description_override"):
        payload["description"] = options["description_override"]

    ecr.status = "ANALYSING"
    db.commit()

    if not background:
        run, _ = run_workflow(payload, options)
        _mark_analysed(ecr_id)
        return run

    # Create the run up front so the caller can subscribe to its event stream
    # before the first agent starts.
    run = registry.create(payload["ecr_id"], options)

    def _target() -> None:
        try:
            run_workflow(payload, options, existing_run=run)
            _mark_analysed(ecr_id)
        except Exception:  # pragma: no cover - already logged and recorded
            logger.warning("ecr.analysis_failed", ecr_id=ecr_id)

    threading.Thread(target=_target, name=f"workflow-{run.workflow_id}", daemon=True).start()
    return run


def _mark_analysed(ecr_id: str) -> None:
    from app.database import session_scope

    with session_scope() as db:
        ecr = ECRRepository(db).get(ecr_id)
        if ecr:
            ecr.status = "ANALYSED"


def latest_report(db: Session, ecr_id: str) -> dict[str, Any] | None:
    """Report from the live run if present, else the last persisted one."""
    run = registry.latest_for_ecr(normalise_ecr_id(ecr_id))
    if run and run.report:
        return run.report
    record = ImpactReportRepository(db).latest_for_ecr(normalise_ecr_id(ecr_id))
    return record.report_json if record else None


def latest_state(ecr_id: str) -> dict[str, Any] | None:
    run = registry.latest_for_ecr(normalise_ecr_id(ecr_id))
    return run.state if run else None
