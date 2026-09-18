"""Natural-language query endpoints."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.dependencies import DbSession
from app.services import chat_service, ecr_service

router = APIRouter(tags=["chat"])


class ChatQuery(BaseModel):
    query: str = Field(..., min_length=3, max_length=2000)
    ecr_id: str | None = None
    run_if_missing: bool = True


class AskRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=2000)


@router.post("/chat/query")
def chat_query(payload: ChatQuery, db: DbSession) -> dict[str, Any]:
    """Ask anything about an ECR.

    Detects the intent and the ECR number, runs the analysis if it has not been
    run yet, then answers from the correlated bundle with citations.
    """
    return chat_service.answer_question(
        db, payload.query, ecr_id=payload.ecr_id, run_if_missing=payload.run_if_missing
    )


@router.post("/ecr/{ecr_id}/ask")
def ask_about_ecr(ecr_id: str, payload: AskRequest, db: DbSession) -> dict[str, Any]:
    """Follow-up question scoped to one ECR (e.g. 'why was TC-1042 selected?')."""
    try:
        ecr_service.get_ecr(db, ecr_id)
    except ecr_service.ECRNotFound as exc:
        raise HTTPException(status_code=404, detail=f"{ecr_id} not found") from exc
    return chat_service.answer_question(db, payload.question, ecr_id=ecr_id)


@router.get("/chat/intent")
def detect_intent(query: str) -> dict[str, Any]:
    """Expose intent detection on its own (useful for the UI and for debugging)."""
    return chat_service.detect_intent(query)
