"""Business/system requirements traced to components and features."""
from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import IdMixin, TimestampMixin


class Requirement(IdMixin, TimestampMixin, Base):
    __tablename__ = "requirements"

    requirement_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(240))
    description: Mapped[str] = mapped_column(Text, default="")
    business_domain: Mapped[str] = mapped_column(String(80), default="General")
    priority: Mapped[str] = mapped_column(String(16), default="MEDIUM")
    status: Mapped[str] = mapped_column(String(32), default="APPROVED")
    component: Mapped[str] = mapped_column(String(64), default="")
    linked_components: Mapped[list[str]] = mapped_column(JSON, default=list)
    features: Mapped[list[str]] = mapped_column(JSON, default=list)
    source_system: Mapped[str] = mapped_column(String(48), default="LOCAL")
    domain: Mapped[str] = mapped_column(String(48), default="commerce")

    def as_dict(self) -> dict[str, Any]:
        return {
            "requirement_id": self.requirement_id,
            "title": self.title,
            "description": self.description,
            "business_domain": self.business_domain,
            "priority": self.priority,
            "status": self.status,
            "component": self.component,
            "linked_components": list(self.linked_components or []),
            "features": list(self.features or []),
            "source_system": self.source_system,
            "domain": self.domain,
        }
