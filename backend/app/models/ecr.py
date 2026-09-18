"""Engineering Change Requests."""
from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import IdMixin, TimestampMixin


class ECR(IdMixin, TimestampMixin, Base):
    __tablename__ = "ecrs"

    ecr_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(240))
    description: Mapped[str] = mapped_column(Text, default="")
    # Analysis state set by the app (NEW, ANALYSING, ANALYSED).
    status: Mapped[str] = mapped_column(String(32), default="NEW")
    change_type: Mapped[str] = mapped_column(String(48), default="UNCLASSIFIED")
    business_domain: Mapped[str] = mapped_column(String(80), default="General")
    requested_by: Mapped[str] = mapped_column(String(120), default="Change Board")
    priority: Mapped[str] = mapped_column(String(16), default="MEDIUM")
    target_release: Mapped[str] = mapped_column(String(48), default="")
    linked_requirements: Mapped[list[str]] = mapped_column(JSON, default=list)
    changed_files: Mapped[list[str]] = mapped_column(JSON, default=list)
    change_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    # Columns of the change-tracking tool export (Type, Status, Severity ...).
    # They are kept exactly as exported and never changed by an analysis.
    record_type: Mapped[str] = mapped_column(String(32), default="ECR")
    lifecycle_status: Mapped[str] = mapped_column(String(48), default="")
    severity: Mapped[str] = mapped_column(String(32), default="")
    assigned_testers: Mapped[list[str]] = mapped_column(JSON, default=list)
    actual_modified_objects: Mapped[list[str]] = mapped_column(JSON, default=list)
    planned_modified_objects: Mapped[list[str]] = mapped_column(JSON, default=list)
    build_resolved_in: Mapped[str] = mapped_column(String(64), default="")
    test_estimate_archived: Mapped[str] = mapped_column(String(32), default="")
    estimate: Mapped[str] = mapped_column(String(32), default="")
    test_estimate: Mapped[str] = mapped_column(String(32), default="")
    creation_date: Mapped[str] = mapped_column(String(40), default="")
    modified_date: Mapped[str] = mapped_column(String(40), default="")
    sit_assigned_testers: Mapped[list[str]] = mapped_column(JSON, default=list)
    test_actual_time: Mapped[str] = mapped_column(String(32), default="")
    affected_test_cases: Mapped[list[str]] = mapped_column(JSON, default=list)
    steps_to_reproduce: Mapped[str] = mapped_column(Text, default="")
    observed_behavior: Mapped[str] = mapped_column(Text, default="")
    expected_behavior: Mapped[str] = mapped_column(Text, default="")
    attachments: Mapped[list[str]] = mapped_column(JSON, default=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ecr_id": self.ecr_id,
            "title": self.title,
            "description": self.description,
            "status": self.status,
            "change_type": self.change_type,
            "business_domain": self.business_domain,
            "requested_by": self.requested_by,
            "priority": self.priority,
            "target_release": self.target_release,
            "linked_requirements": list(self.linked_requirements or []),
            "changed_files": list(self.changed_files or []),
            "change_metadata": dict(self.change_metadata or {}),
            "record_type": self.record_type or "ECR",
            "lifecycle_status": self.lifecycle_status or "",
            "severity": self.severity or "",
            "assigned_testers": list(self.assigned_testers or []),
            "actual_modified_objects": list(self.actual_modified_objects or []),
            "planned_modified_objects": list(self.planned_modified_objects or []),
            "build_resolved_in": self.build_resolved_in or "",
            "test_estimate_archived": self.test_estimate_archived or "",
            "estimate": self.estimate or "",
            "test_estimate": self.test_estimate or "",
            "creation_date": self.creation_date or "",
            "modified_date": self.modified_date or "",
            "sit_assigned_testers": list(self.sit_assigned_testers or []),
            "test_actual_time": self.test_actual_time or "",
            "affected_test_cases": list(self.affected_test_cases or []),
            "steps_to_reproduce": self.steps_to_reproduce or "",
            "observed_behavior": self.observed_behavior or "",
            "expected_behavior": self.expected_behavior or "",
            "attachments": list(self.attachments or []),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
