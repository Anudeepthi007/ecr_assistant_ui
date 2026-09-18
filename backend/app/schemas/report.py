"""Final report schema (Agent 10)."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import ConfidenceBand
from app.schemas.ecr import ECRUnderstanding
from app.schemas.impact import (
    CodeImpactAnalysis,
    DefectAnalysis,
    DependencyAnalysis,
    ImpactAssessment,
    RequirementAnalysis,
)
from app.schemas.test_case import TestPrioritization, TestSelection


class ReportSection(BaseModel):
    key: str
    title: str
    body: str = ""
    data: dict[str, Any] = Field(default_factory=dict)


class ConfidenceReport(BaseModel):
    overall: float = 0.0
    band: ConfidenceBand = ConfidenceBand.MEDIUM
    per_step: dict[str, float] = Field(default_factory=dict)
    penalties: list[str] = Field(default_factory=list)


class ECRIntelligenceReport(BaseModel):
    workflow_id: str
    ecr_id: str
    generated_at: datetime
    title: str = ""
    executive_summary: str = ""
    ecr_overview: dict[str, Any] = Field(default_factory=dict)
    change_classification: ECRUnderstanding | None = None
    retrieval_plan: dict[str, Any] = Field(default_factory=dict)
    correlation_review: dict[str, Any] = Field(default_factory=dict)
    requirement_analysis: RequirementAnalysis | None = None
    defect_analysis: DefectAnalysis | None = None
    defect_insights: dict[str, Any] = Field(default_factory=dict)
    defect_summary: str = ""
    code_impact: CodeImpactAnalysis | None = None
    dependency_analysis: DependencyAnalysis | None = None
    impact_assessment: ImpactAssessment | None = None
    test_selection: TestSelection | None = None
    test_prioritization: TestPrioritization | None = None
    mitigations: list[str] = Field(default_factory=list)
    confidence: ConfidenceReport = Field(default_factory=ConfidenceReport)
    execution_trace: list[dict[str, Any]] = Field(default_factory=list)
    sections: list[ReportSection] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    errors: list[dict[str, Any]] = Field(default_factory=list)
    approval: dict[str, Any] = Field(default_factory=dict)
