"""Test discovery / selection / prioritisation schemas."""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.common import Priority


class TestCaseRead(BaseModel):
    test_case_id: str
    title: str
    description: str = ""
    feature: str = ""
    suite: str = "Regression"
    component: str = ""
    linked_components: list[str] = Field(default_factory=list)
    requirement_id: str = ""
    test_type: str = "FUNCTIONAL"
    test_level: str = "SYSTEM"
    automation_status: str = "AUTOMATED"
    folder: str = ""
    optimization_technique: str = "Default"
    test_polarity: str = "Positive"
    test_technique: str = ""
    retired: bool = False
    scorable: bool = True
    domain: str = "commerce"
    average_execution_time: float = 60.0
    historical_failure_rate: float = 0.0
    tags: list[str] = Field(default_factory=list)


class TestScoreBreakdown(BaseModel):
    requirement_match: float = 0.0
    component_match: float = 0.0
    dependency_relevance: float = 0.0
    historical_failure: float = 0.0
    semantic_similarity: float = 0.0


class SelectedTest(TestCaseRead):
    relevance_score: float = Field(0.0, ge=0.0, le=100.0)
    priority: Priority = Priority.P3
    breakdown: TestScoreBreakdown = Field(default_factory=TestScoreBreakdown)
    reasons: list[str] = Field(default_factory=list)
    reason: str = ""
    execution_order: int = 0
    selected: bool = True


class TestDiscovery(BaseModel):
    candidate_tests: list[TestCaseRead] = Field(default_factory=list)
    total_available: int = 0
    discovery_channels: dict[str, int] = Field(default_factory=dict)
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    reasoning: str = ""


class TestSelection(BaseModel):
    selected_tests: list[SelectedTest] = Field(default_factory=list)
    excluded_count: int = 0
    total_available: int = 0
    total_candidates: int = 0
    reduction_percentage: float = 0.0
    estimated_duration_minutes: float = 0.0
    baseline_duration_minutes: float = 0.0
    priority_distribution: dict[str, int] = Field(default_factory=dict)
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    reasoning: str = ""


class TestPrioritization(BaseModel):
    prioritized_tests: list[SelectedTest] = Field(default_factory=list)
    waves: dict[str, list[str]] = Field(default_factory=dict)
    estimated_duration_minutes: float = 0.0
    critical_path_minutes: float = 0.0
    strategy: str = ""
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    reasoning: str = ""
