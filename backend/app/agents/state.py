"""Shared LangGraph workflow state and the agent catalogue.

The platform has exactly three agents - Retrieval, Correlation, Summarization.
Everything else in the workflow is a *step* owned by one of them. Agents only
exchange validated Pydantic payloads (serialised to dicts so the state stays
checkpointable). Keys that several steps write carry reducers.
"""
from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from app.schemas.agent import AgentDescriptor


def merge_dicts(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    merged = dict(left or {})
    merged.update(right or {})
    return merged


def merge_unique(left: list[str], right: list[str]) -> list[str]:
    seen = list(left or [])
    for item in right or []:
        if item not in seen:
            seen.append(item)
    return seen


class ECRWorkflowState(TypedDict, total=False):
    # -- run context ------------------------------------------------------
    workflow_id: str
    ecr_id: str
    ecr_input: dict[str, Any]
    options: dict[str, Any]

    # -- step outputs -----------------------------------------------------
    ecr_analysis: dict[str, Any]
    retrieval_plan: dict[str, Any]
    plan: list[str]
    plan_detail: dict[str, Any]
    skipped_steps: Annotated[list[str], merge_unique]
    requirements: list[dict[str, Any]]
    requirement_analysis: dict[str, Any]
    defects: list[dict[str, Any]]
    defect_analysis: dict[str, Any]
    defect_insights: dict[str, Any]
    defect_summary: str
    comments: list[dict[str, Any]]
    evidence: list[dict[str, Any]]
    collaboration_analysis: dict[str, Any]
    correlation: dict[str, Any]
    correlation_review: dict[str, Any]
    code_impact: dict[str, Any]
    dependency_analysis: dict[str, Any]
    impact_analysis: dict[str, Any]
    discovered_tests: list[dict[str, Any]]
    test_discovery: dict[str, Any]
    selected_tests: list[dict[str, Any]]
    test_selection: dict[str, Any]
    prioritized_tests: list[dict[str, Any]]
    test_prioritization: dict[str, Any]
    approval: dict[str, Any]
    question: str
    final_answer: str
    answer_context: dict[str, Any]
    answer_citations: list[str]
    final_report: dict[str, Any]

    # -- telemetry (written by every step -> reducers) --------------------
    execution_trace: Annotated[list[dict[str, Any]], operator.add]
    errors: Annotated[list[dict[str, Any]], operator.add]
    step_confidence: Annotated[dict[str, float], merge_dicts]
    tools_used: Annotated[dict[str, Any], merge_dicts]


# The only agents in the system.
AGENT_CATALOG: list[AgentDescriptor] = [
    AgentDescriptor(
        key="retrieval_agent",
        name="Retrieval Agent",
        purpose=(
            "Given an ECR number, use the LLM to plan what to search for, then gather everything "
            "that exists about it: the change record, traced and semantically matched "
            "requirements, historical defects, code impact, dependency reach, review comments "
            "and evidence artefacts."
        ),
        tools=[
            "classify_change",
            "extract_entities",
            "llm.plan_retrieval",
            "build_plan",
            "trace_requirements",
            "semantic_requirement_search",
            "keyword_requirement_search",
            "analyze_changed_files",
            "walk_import_graph",
            "semantic_defect_search",
            "defects_by_component",
            "build_graph",
            "downstream_walk",
            "upstream_walk",
            "comments_for_ecr",
            "evidence_for_ecr",
        ],
    ),
    AgentDescriptor(
        key="correlation_agent",
        name="Correlation Agent",
        purpose=(
            "Connect every retrieved artefact to the ECR with typed, explained links, find the "
            "impacted components, decide which regression tests actually matter, check "
            "whether each related defect could happen again, and use the LLM to find the "
            "contradictions and gaps across the correlated sources."
        ),
        tools=[
            "component_impact",
            "tests_by_requirement",
            "tests_by_component",
            "semantic_test_search",
            "selection_engine.select",
            "selection_engine.prioritise",
            "build_correlation_graph",
            "analyze_defects",
            "llm.review_correlation",
        ],
        depends_on=["retrieval_agent"],
    ),
    AgentDescriptor(
        key="summarization_agent",
        name="Summarization Agent",
        purpose=(
            "Answer the user's question from the correlated bundle with citations, explain the "
            "related defects in plain language, and publish the full ECR intelligence report."
        ),
        tools=["build_answer_context", "llm.summarize", "report_service.build"],
        depends_on=["correlation_agent"],
    ),
]

# Steps each agent runs, in order. Keys match the step keys on the event stream.
AGENT_STEPS: dict[str, list[dict[str, str]]] = {
    "retrieval_agent": [
        {"key": "understand_ecr", "name": "Understand the ECR"},
        {"key": "gather_evidence", "name": "Gather evidence"},
    ],
    "correlation_agent": [
        {"key": "assess_impact", "name": "Assess impact"},
        {"key": "select_tests", "name": "Select regression tests"},
    ],
    "summarization_agent": [
        {"key": "summarize", "name": "Summarize and report"},
    ],
}

AGENT_BY_KEY = {descriptor.key: descriptor for descriptor in AGENT_CATALOG}
STEP_NAMES = {step["key"]: step["name"] for steps in AGENT_STEPS.values() for step in steps}


def initial_state(
    workflow_id: str, ecr_input: dict[str, Any], options: dict[str, Any] | None = None
) -> ECRWorkflowState:
    return ECRWorkflowState(
        workflow_id=workflow_id,
        ecr_id=ecr_input.get("ecr_id", ""),
        ecr_input=ecr_input,
        options=options or {},
        skipped_steps=[],
        execution_trace=[],
        errors=[],
        step_confidence={},
        tools_used={},
    )
