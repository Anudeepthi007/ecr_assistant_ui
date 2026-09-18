"""Test cases and their execution history."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import IdMixin, TimestampMixin, utcnow


class TestCase(IdMixin, TimestampMixin, Base):
    __tablename__ = "test_cases"

    test_case_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(240))
    description: Mapped[str] = mapped_column(Text, default="")
    feature: Mapped[str] = mapped_column(String(120), default="")
    suite: Mapped[str] = mapped_column(String(120), default="Regression")
    component: Mapped[str] = mapped_column(String(64), default="")
    linked_components: Mapped[list[str]] = mapped_column(JSON, default=list)
    requirement_id: Mapped[str] = mapped_column(String(64), default="")
    test_type: Mapped[str] = mapped_column(String(32), default="FUNCTIONAL")
    test_level: Mapped[str] = mapped_column(String(32), default="SYSTEM")
    automation_status: Mapped[str] = mapped_column(String(32), default="AUTOMATED")
    # Fields carried over from enterprise test-management exports
    # (folder / optimization technique / positive-negative / design technique).
    folder: Mapped[str] = mapped_column(String(120), default="")
    optimization_technique: Mapped[str] = mapped_column(String(64), default="Default")
    test_polarity: Mapped[str] = mapped_column(String(16), default="Positive")
    test_technique: Mapped[str] = mapped_column(String(80), default="")
    retired: Mapped[bool] = mapped_column(default=False)
    scorable: Mapped[bool] = mapped_column(default=True)
    domain: Mapped[str] = mapped_column(String(48), default="commerce")
    average_execution_time: Mapped[float] = mapped_column(Float, default=60.0)
    historical_failure_rate: Mapped[float] = mapped_column(Float, default=0.05)
    last_executed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    source_system: Mapped[str] = mapped_column(String(48), default="LOCAL")

    def as_dict(self) -> dict[str, Any]:
        return {
            "test_case_id": self.test_case_id,
            "title": self.title,
            "description": self.description,
            "feature": self.feature,
            "suite": self.suite,
            "component": self.component,
            "linked_components": list(self.linked_components or []),
            "requirement_id": self.requirement_id,
            "test_type": self.test_type,
            "test_level": self.test_level,
            "automation_status": self.automation_status,
            "folder": self.folder,
            "optimization_technique": self.optimization_technique,
            "test_polarity": self.test_polarity,
            "test_technique": self.test_technique,
            "retired": self.retired,
            "scorable": self.scorable,
            "domain": self.domain,
            "average_execution_time": self.average_execution_time,
            "historical_failure_rate": self.historical_failure_rate,
            "tags": list(self.tags or []),
            "source_system": self.source_system,
        }


class TestExecution(IdMixin, Base):
    __tablename__ = "test_executions"

    test_case_pk: Mapped[int] = mapped_column(ForeignKey("test_cases.id", ondelete="CASCADE"))
    test_case_id: Mapped[str] = mapped_column(String(64), index=True)
    result: Mapped[str] = mapped_column(String(16), default="PASS")
    duration_seconds: Mapped[float] = mapped_column(Float, default=60.0)
    build_id: Mapped[str] = mapped_column(String(64), default="")
    defect_id: Mapped[str] = mapped_column(String(64), default="")
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    def as_dict(self) -> dict[str, Any]:
        return {
            "test_case_id": self.test_case_id,
            "result": self.result,
            "duration_seconds": self.duration_seconds,
            "build_id": self.build_id,
            "defect_id": self.defect_id,
            "executed_at": self.executed_at.isoformat() if self.executed_at else None,
        }
