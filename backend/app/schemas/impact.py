"""Impact analysis schemas - outputs of agents 2 to 6."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class RequirementMatch(BaseModel):
    requirement_id: str
    title: str
    description: str = ""
    business_domain: str = ""
    priority: str = "MEDIUM"
    component: str = ""
    linked_components: list[str] = Field(default_factory=list)
    features: list[str] = Field(default_factory=list)
    relevance: float = Field(0.0, ge=0.0, le=100.0)
    match_type: str = "SEMANTIC"
    reason: str = ""


class RequirementAnalysis(BaseModel):
    matched_requirements: list[RequirementMatch] = Field(default_factory=list)
    impacted_components: list[str] = Field(default_factory=list)
    searched_count: int = 0
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    reasoning: str = ""


class DefectMatch(BaseModel):
    defect_id: str
    title: str
    severity: str = "MEDIUM"
    status: str = "CLOSED"
    root_cause: str = ""
    root_cause_category: str = ""
    affected_component: str = ""
    similarity: float = Field(0.0, ge=0.0, le=100.0)
    escaped_to_production: bool = False
    reason: str = ""


class DefectAnalysis(BaseModel):
    similar_defects: list[DefectMatch] = Field(default_factory=list)
    defect_prone_components: list[str] = Field(default_factory=list)
    recurring_failure_patterns: list[str] = Field(default_factory=list)
    severity_distribution: dict[str, int] = Field(default_factory=dict)
    searched_count: int = 0
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    reasoning: str = ""


class CodeSymbol(BaseModel):
    file: str
    symbol: str
    kind: str = "function"
    component: str = ""
    calls: list[str] = Field(default_factory=list)


class CodeImpactAnalysis(BaseModel):
    directly_impacted_files: list[str] = Field(default_factory=list)
    impacted_symbols: list[CodeSymbol] = Field(default_factory=list)
    impacted_services: list[str] = Field(default_factory=list)
    potentially_impacted_services: list[str] = Field(default_factory=list)
    impacted_apis: list[str] = Field(default_factory=list)
    database_entities: list[str] = Field(default_factory=list)
    change_surface: float = Field(0.0, ge=0.0, le=1.0)
    language_analyzers: list[str] = Field(default_factory=list)
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    reasoning: str = ""


class DependencyEdge(BaseModel):
    source: str
    target: str
    dependency_type: str = "SYNC_API"
    criticality: str = "MEDIUM"


class DependencyNode(BaseModel):
    component_id: str
    name: str
    type: str = "SERVICE"
    business_criticality: str = "MEDIUM"
    distance: int = 0
    relation: str = "SEED"


class DependencyAnalysis(BaseModel):
    seed_components: list[str] = Field(default_factory=list)
    direct_dependencies: list[str] = Field(default_factory=list)
    indirect_dependencies: list[str] = Field(default_factory=list)
    upstream_components: list[str] = Field(default_factory=list)
    downstream_components: list[str] = Field(default_factory=list)
    critical_dependency_paths: list[list[str]] = Field(default_factory=list)
    blast_radius: int = 0
    nodes: list[DependencyNode] = Field(default_factory=list)
    edges: list[DependencyEdge] = Field(default_factory=list)
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    reasoning: str = ""


class ComponentImpact(BaseModel):
    component_id: str
    name: str
    type: str = "SERVICE"
    business_criticality: str = "MEDIUM"
    impact_type: str = "DIRECT"
    impact_score: float = 0.0
    distance: int = 0
    reasons: list[str] = Field(default_factory=list)


class ImpactAssessment(BaseModel):
    directly_impacted_components: list[ComponentImpact] = Field(default_factory=list)
    indirectly_impacted_components: list[ComponentImpact] = Field(default_factory=list)
    functional_impact: str = ""
    technical_impact: str = ""
    business_impact: str = ""
    mitigations: list[str] = Field(default_factory=list)
    executive_summary: str = ""
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    degraded_inputs: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
