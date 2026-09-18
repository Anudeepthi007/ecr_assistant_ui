"""Persisted impact analysis reports and user feedback."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import IdMixin, utcnow


class ImpactReport(IdMixin, Base):
    __tablename__ = "impact_reports"

    workflow_id: Mapped[str] = mapped_column(String(64), index=True)
    ecr_id: Mapped[str] = mapped_column(String(64), index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    total_tests: Mapped[int] = mapped_column(Integer, default=0)
    selected_tests: Mapped[int] = mapped_column(Integer, default=0)
    reduction_percentage: Mapped[float] = mapped_column(Float, default=0.0)
    execution_time: Mapped[float] = mapped_column(Float, default=0.0)
    approval_status: Mapped[str] = mapped_column(String(24), default="NOT_REQUIRED")
    report_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    def summary(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "ecr_id": self.ecr_id,
            "confidence": self.confidence,
            "total_tests": self.total_tests,
            "selected_tests": self.selected_tests,
            "reduction_percentage": self.reduction_percentage,
            "execution_time": self.execution_time,
            "approval_status": self.approval_status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Feedback(IdMixin, Base):
    __tablename__ = "feedback"

    ecr_id: Mapped[str] = mapped_column(String(64), index=True)
    workflow_id: Mapped[str] = mapped_column(String(64), default="")
    target_type: Mapped[str] = mapped_column(String(32), default="RECOMMENDATION")
    target_id: Mapped[str] = mapped_column(String(64), default="")
    useful: Mapped[bool] = mapped_column(default=True)
    comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ecr_id": self.ecr_id,
            "workflow_id": self.workflow_id,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "useful": self.useful,
            "comment": self.comment,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
