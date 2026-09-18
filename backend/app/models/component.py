"""Components (services, modules, databases) of the sample enterprise landscape."""
from __future__ import annotations

from sqlalchemy import Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import IdMixin, TimestampMixin


class Component(IdMixin, TimestampMixin, Base):
    __tablename__ = "components"

    component_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    type: Mapped[str] = mapped_column(String(48))
    business_criticality: Mapped[str] = mapped_column(String(16), default="MEDIUM")
    criticality_score: Mapped[float] = mapped_column(Float, default=0.5)
    owner: Mapped[str] = mapped_column(String(120), default="Unassigned")
    repository: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    business_domain: Mapped[str] = mapped_column(String(80), default="General")
    domain: Mapped[str] = mapped_column(String(48), default="commerce")

    def as_dict(self) -> dict:
        return {
            "component_id": self.component_id,
            "name": self.name,
            "type": self.type,
            "business_criticality": self.business_criticality,
            "criticality_score": self.criticality_score,
            "owner": self.owner,
            "repository": self.repository,
            "description": self.description,
            "business_domain": self.business_domain,
            "domain": self.domain,
        }
