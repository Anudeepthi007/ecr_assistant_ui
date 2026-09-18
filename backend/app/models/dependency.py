"""Directed dependency edges between components."""
from __future__ import annotations

from sqlalchemy import Float, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import IdMixin, TimestampMixin
from app.models.component import Component


class Dependency(IdMixin, TimestampMixin, Base):
    __tablename__ = "dependencies"
    __table_args__ = (
        UniqueConstraint("source_component_id", "target_component_id", name="uq_dependency_edge"),
    )

    source_component_id: Mapped[int] = mapped_column(ForeignKey("components.id", ondelete="CASCADE"))
    target_component_id: Mapped[int] = mapped_column(ForeignKey("components.id", ondelete="CASCADE"))
    dependency_type: Mapped[str] = mapped_column(String(32), default="SYNC_API")
    criticality: Mapped[str] = mapped_column(String(16), default="MEDIUM")
    weight: Mapped[float] = mapped_column(Float, default=0.5)
    description: Mapped[str] = mapped_column(String(255), default="")

    source: Mapped[Component] = relationship(foreign_keys=[source_component_id], lazy="joined")
    target: Mapped[Component] = relationship(foreign_keys=[target_component_id], lazy="joined")

    def as_dict(self) -> dict:
        return {
            "source": self.source.component_id if self.source else None,
            "source_name": self.source.name if self.source else None,
            "target": self.target.component_id if self.target else None,
            "target_name": self.target.name if self.target else None,
            "dependency_type": self.dependency_type,
            "criticality": self.criticality,
            "weight": self.weight,
            "description": self.description,
        }
