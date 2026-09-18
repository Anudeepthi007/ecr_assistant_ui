"""ECR request/response schemas plus the ECR Understanding Agent contract."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.common import ChangeType


class ECRCreate(BaseModel):
    ecr_id: str | None = Field(
        None, description="Optional. Auto-generated (ECR-YYYY-NNN) when omitted."
    )
    title: str = Field(..., min_length=3, max_length=240)
    description: str = Field("", max_length=8000)
    business_domain: str = "General"
    requested_by: str = "Change Board"
    priority: str = "MEDIUM"
    target_release: str = ""
    linked_requirements: list[str] = Field(default_factory=list)
    changed_files: list[str] = Field(default_factory=list)
    change_metadata: dict[str, Any] = Field(default_factory=dict)

    # Change-tracking export columns (all optional).
    record_type: str = "ECR"
    lifecycle_status: str = ""
    severity: str = ""
    assigned_testers: list[str] = Field(default_factory=list)
    actual_modified_objects: list[str] = Field(default_factory=list)
    planned_modified_objects: list[str] = Field(default_factory=list)
    build_resolved_in: str = ""
    test_estimate_archived: str = ""
    estimate: str = ""
    test_estimate: str = ""
    creation_date: str = ""
    modified_date: str = ""
    sit_assigned_testers: list[str] = Field(default_factory=list)
    test_actual_time: str = ""
    affected_test_cases: list[str] = Field(default_factory=list)
    steps_to_reproduce: str = ""
    observed_behavior: str = ""
    expected_behavior: str = ""
    attachments: list[str] = Field(default_factory=list)

    @field_validator("ecr_id")
    @classmethod
    def _strip(cls, value: str | None) -> str | None:
        return value.strip().upper() if value else None


class ECRRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ecr_id: str
    title: str
    description: str
    status: str
    change_type: str
    business_domain: str
    requested_by: str
    priority: str
    target_release: str
    linked_requirements: list[str] = Field(default_factory=list)
    changed_files: list[str] = Field(default_factory=list)
    change_metadata: dict[str, Any] = Field(default_factory=dict)

    # Change-tracking export columns (all optional).
    record_type: str = "ECR"
    lifecycle_status: str = ""
    severity: str = ""
    assigned_testers: list[str] = Field(default_factory=list)
    actual_modified_objects: list[str] = Field(default_factory=list)
    planned_modified_objects: list[str] = Field(default_factory=list)
    build_resolved_in: str = ""
    test_estimate_archived: str = ""
    estimate: str = ""
    test_estimate: str = ""
    creation_date: str = ""
    modified_date: str = ""
    sit_assigned_testers: list[str] = Field(default_factory=list)
    test_actual_time: str = ""
    affected_test_cases: list[str] = Field(default_factory=list)
    steps_to_reproduce: str = ""
    observed_behavior: str = ""
    expected_behavior: str = ""
    attachments: list[str] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class AnalyzeRequest(BaseModel):
    """Options for a workflow run."""

    human_in_the_loop: bool | None = None
    force_full_analysis: bool = False
    description_override: str | None = None
    demo_mode: bool = False


class ECRUnderstanding(BaseModel):
    """Structured output of Agent 1 (ECR Understanding)."""

    ecr_id: str
    change_type: ChangeType = ChangeType.MIXED
    change_type_scores: dict[str, float] = Field(default_factory=dict)
    business_domain: str = "General"
    affected_features: list[str] = Field(default_factory=list)
    technical_keywords: list[str] = Field(default_factory=list)
    candidate_components: list[str] = Field(default_factory=list)
    risk_indicators: list[str] = Field(default_factory=list)
    change_complexity: float = Field(0.5, ge=0.0, le=1.0)
    summary: str = ""
    confidence: float = Field(0.8, ge=0.0, le=1.0)
