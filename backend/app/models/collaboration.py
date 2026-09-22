"""Human artifacts attached to a change: review comments and evidence.

These are the sources engineers currently read by hand across several systems
(ADO work item discussions, review threads, test evidence attachments), which
is exactly the manual effort the assistant removes.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import IdMixin, utcnow


class Comment(IdMixin, Base):
    """A discussion entry on an ECR, requirement, defect or test case."""

    __tablename__ = "comments"

    comment_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    ecr_id: Mapped[str] = mapped_column(String(64), index=True, default="")
    target_type: Mapped[str] = mapped_column(String(32), default="ECR")
    target_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    author: Mapped[str] = mapped_column(String(120), default="")
    author_role: Mapped[str] = mapped_column(String(80), default="Engineer")
    body: Mapped[str] = mapped_column(Text, default="")
    sentiment: Mapped[str] = mapped_column(String(16), default="NEUTRAL")
    category: Mapped[str] = mapped_column(String(48), default="DISCUSSION")
    source_system: Mapped[str] = mapped_column(String(48), default="AZURE_DEVOPS")
    references: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    def as_dict(self) -> dict[str, Any]:
        return {
            "comment_id": self.comment_id,
            "ecr_id": self.ecr_id,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "author": self.author,
            "author_role": self.author_role,
            "body": self.body,
            "sentiment": self.sentiment,
            "category": self.category,
            "source_system": self.source_system,
            "references": list(self.references or []),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Evidence(IdMixin, Base):
    """An artifact proving something about the change (run, log, review, doc)."""

    __tablename__ = "evidence"

    evidence_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    ecr_id: Mapped[str] = mapped_column(String(64), index=True, default="")
    target_type: Mapped[str] = mapped_column(String(32), default="TEST_CASE")
    target_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    title: Mapped[str] = mapped_column(String(240), default="")
    evidence_type: Mapped[str] = mapped_column(String(48), default="TEST_RUN")
    summary: Mapped[str] = mapped_column(Text, default="")
    outcome: Mapped[str] = mapped_column(String(32), default="PASS")
    uri: Mapped[str] = mapped_column(String(300), default="")
    source_system: Mapped[str] = mapped_column(String(48), default="AZURE_DEVOPS")
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    def as_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "ecr_id": self.ecr_id,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "title": self.title,
            "evidence_type": self.evidence_type,
            "summary": self.summary,
            "outcome": self.outcome,
            "uri": self.uri,
            "source_system": self.source_system,
            "confidence": self.confidence,
            "captured_at": self.captured_at.isoformat() if self.captured_at else None,
        }
