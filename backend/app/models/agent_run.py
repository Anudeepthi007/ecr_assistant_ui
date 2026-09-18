"""Persisted agent/workflow telemetry."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import IdMixin, utcnow


class AgentRun(IdMixin, Base):
    __tablename__ = "agent_runs"

    workflow_id: Mapped[str] = mapped_column(String(64), index=True)
    ecr_id: Mapped[str] = mapped_column(String(64), index=True, default="")
    agent_name: Mapped[str] = mapped_column(String(80))
    agent_key: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(24), default="COMPLETED")
    action: Mapped[str] = mapped_column(String(240), default="")
    input: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    output: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    reasoning: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    execution_time: Mapped[float] = mapped_column(Float, default=0.0)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    def as_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "ecr_id": self.ecr_id,
            "agent": self.agent_name,
            "agent_key": self.agent_key,
            "status": self.status,
            "action": self.action,
            "input": dict(self.input or {}),
            "output": dict(self.output or {}),
            "reasoning": self.reasoning,
            "confidence": self.confidence,
            "execution_time": self.execution_time,
            "error": self.error,
            "timestamp": self.created_at.isoformat() if self.created_at else None,
        }
