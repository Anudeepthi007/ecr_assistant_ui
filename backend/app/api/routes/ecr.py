"""ECR CRUD and catalogue endpoints."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, status

from app.dependencies import DbSession
from app.models import Comment, Evidence
from app.repositories import ECRRepository, ImpactReportRepository
from app.schemas.ecr import ECRCreate, ECRRead
from app.services import ecr_service

router = APIRouter(prefix="/ecr", tags=["ecr"])


@router.get("", response_model=list[ECRRead])
def list_ecrs(db: DbSession, search: str | None = None, limit: int = Query(50, le=200)):
    repository = ECRRepository(db)
    rows = repository.search(search, limit) if search else repository.list(limit)
    return [ECRRead.model_validate(row.as_dict()) for row in rows]


@router.post("", response_model=ECRRead, status_code=status.HTTP_201_CREATED)
def create_ecr(payload: ECRCreate, db: DbSession):
    try:
        ecr = ecr_service.create_ecr(db, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return ECRRead.model_validate(ecr.as_dict())


@router.get("/{ecr_id}", response_model=ECRRead)
def get_ecr(ecr_id: str, db: DbSession):
    try:
        ecr = ecr_service.get_ecr(db, ecr_id)
    except ecr_service.ECRNotFound as exc:
        raise HTTPException(status_code=404, detail=f"{ecr_id} not found") from exc
    return ECRRead.model_validate(ecr.as_dict())


@router.get("/{ecr_id}/sources")
def ecr_sources(ecr_id: str, db: DbSession) -> dict[str, Any]:
    """Everything attached to the ECR before any correlation is applied.

    Useful on its own: it is the raw multi-source view a user would otherwise
    assemble by opening several systems.
    """
    try:
        ecr = ecr_service.get_ecr(db, ecr_id)
    except ecr_service.ECRNotFound as exc:
        raise HTTPException(status_code=404, detail=f"{ecr_id} not found") from exc
    normalised = ecr.ecr_id
    comments = db.query(Comment).filter(Comment.ecr_id == normalised).all()
    evidence = db.query(Evidence).filter(Evidence.ecr_id == normalised).all()
    reports = ImpactReportRepository(db)
    latest = reports.latest_for_ecr(normalised)
    return {
        "ecr": ecr.as_dict(),
        "comments": [row.as_dict() for row in comments],
        "evidence": [row.as_dict() for row in evidence],
        "last_analysis": latest.summary() if latest else None,
    }


@router.get("/{ecr_id}/history")
def ecr_history(ecr_id: str, db: DbSession) -> list[dict[str, Any]]:
    """Previous analyses of this ECR."""
    normalised = ecr_service.normalise_ecr_id(ecr_id)
    return [
        report.summary()
        for report in ImpactReportRepository(db).all_reports()
        if report.ecr_id == normalised
    ]
