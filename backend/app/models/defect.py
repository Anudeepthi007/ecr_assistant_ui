"""Historical defects and production incidents."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import IdMixin, TimestampMixin, utcnow


class Defect(IdMixin, TimestampMixin, Base):
    __tablename__ = "defects"

    defect_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(240))
    description: Mapped[str] = mapped_column(Text, default="")
    severity: Mapped[str] = mapped_column(String(16), default="MEDIUM")
    status: Mapped[str] = mapped_column(String(32), default="CLOSED")
    root_cause: Mapped[str] = mapped_column(Text, default="")
    root_cause_category: Mapped[str] = mapped_column(String(80), default="")
    affected_component: Mapped[str] = mapped_column(String(64), default="")
    related_components: Mapped[list[str]] = mapped_column(JSON, default=list)
    linked_requirements: Mapped[list[str]] = mapped_column(JSON, default=list)
    escaped_to_production: Mapped[bool] = mapped_column(default=False)
    reopen_count: Mapped[int] = mapped_column(default=0)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    severity_weight: Mapped[float] = mapped_column(Float, default=0.5)

    def as_dict(self) -> dict[str, Any]:
        return {
            "defect_id": self.defect_id,
            "title": self.title,
            "description": self.description,
            "severity": self.severity,
            "status": self.status,
            "root_cause": self.root_cause,
            "root_cause_category": self.root_cause_category,
            "affected_component": self.affected_component,
            "related_components": list(self.related_components or []),
            "linked_requirements": list(self.linked_requirements or []),
            "escaped_to_production": self.escaped_to_production,
            "reopen_count": self.reopen_count,
            "detected_at": self.detected_at.isoformat() if self.detected_at else None,
        }
