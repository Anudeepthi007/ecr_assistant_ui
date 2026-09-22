"""The five steps. The three agents run them; nothing else is traced.

    Retrieval Agent      1. understand_ecr   classify the change, LLM plans the search,
                                             plan the investigation
                         2. gather_evidence  requirements, code impact, related defects,
                                             [dependencies], review comments and evidence
    Correlation Agent    3. assess_impact    impacted components and recommended actions
                         4. select_tests     discover, select and order regression tests,
                                             link every artifact to the ECR, analyse defects,
                                             LLM reviews the correlated bundle
    Summarization Agent  5. summarize        plain-language answer, defect summary, report

Every agent reasons with the LLM once it has something to reason about: the
Retrieval Agent decides what to search for, the Correlation Agent finds the
contradictions and gaps across sources, the Summarization Agent writes the
answer and the defect summary. That is exactly one LLM request per agent - three
per analysis. Each LLM part has a rule-based fallback, so no key still means a result.

Each step calls smaller *parts* (the functions in the sibling modules). A part
that fails is recorded and skipped, so one missing source lowers confidence
instead of stopping the analysis.
"""
from __future__ import annotations

from typing import Any, Callable

from app.agents.nodes.code_impact import code_impact_step
from app.agents.nodes.collaboration import collaboration_step
from app.agents.nodes.correlation import correlation_step
from app.agents.nodes.correlation_review import correlation_review_step
from app.agents.nodes.defect_insights import defect_insights_step
from app.agents.nodes.dependencies import dependency_step
from app.agents.nodes.ecr_understanding import ecr_understanding_step
from app.agents.nodes.historical_defects import defect_step
from app.agents.nodes.impact_assessment import impact_assessment_step
from app.agents.nodes.planning import planning_step
from app.agents.nodes.regression_tests import (
    test_discovery_step,
    test_prioritization_step,
    test_selection_step,
)
from app.agents.nodes.requirements import requirement_step
from app.agents.nodes.retrieval_planning import retrieval_planning_step
from app.agents.nodes.summarization import report_step, summarization_step
from app.agents.runtime import agent_step, build_view, merge_partial, registry
from app.logging import get_logger

logger = get_logger("ecr.steps")

Part = Callable[[dict[str, Any]], dict[str, Any]]


def _part(
    state: dict[str, Any],
    acc: dict[str, Any],
    parts: list[dict[str, Any]],
    key: str,
    fn: Part,
    *,
    owner: str,
    required: bool = False,
) -> None:
    """Run one part against state + what this step produced so far."""
    try:
        out = dict(fn(build_view(state, acc)) or {})
    except Exception as exc:
        if required:
            raise
        logger.warning("step.part_failed", part=key, error=str(exc))
        error = {"agent": owner, "agent_key": key, "error": str(exc), "critical": False}
        run = registry.get(state.get("workflow_id", ""))
        if run:
            run.errors.append(error)
        merge_partial(acc, {"errors": [error], "skipped_steps": [key]})
        parts.append({"confidence": None, "reasoning": f"{key.replace('_', ' ').capitalize()} unavailable."})
        return
    parts.append({"confidence": out.pop("_confidence", None), "reasoning": str(out.pop("_reasoning", ""))})
    out.pop("_summary", None)
    merge_partial(acc, out)


def _finish(acc: dict[str, Any], parts: list[dict[str, Any]], summary: dict[str, Any]) -> dict[str, Any]:
    confidences = [part["confidence"] for part in parts if part["confidence"]]
    acc["_confidence"] = round(sum(confidences) / len(confidences), 3) if confidences else 0.5
    acc["_reasoning"] = " ".join(part["reasoning"] for part in parts if part["reasoning"])
    acc["_summary"] = summary
    return acc


RETRIEVAL = "Retrieval Agent"
CORRELATION = "Correlation Agent"
SUMMARIZATION = "Summarization Agent"


@agent_step("understand_ecr", RETRIEVAL, "Understanding the ECR and planning the investigation", critical=True)
def understand_ecr(state: dict[str, Any]) -> dict[str, Any]:
    acc: dict[str, Any] = {}
    parts: list[dict[str, Any]] = []
    _part(state, acc, parts, "ecr_understanding", ecr_understanding_step, owner=RETRIEVAL, required=True)
    # The LLM plans the search between the rule classification and the plan it may extend.
    _part(state, acc, parts, "retrieval_planning", retrieval_planning_step, owner=RETRIEVAL)
    _part(state, acc, parts, "planning", planning_step, owner=RETRIEVAL, required=True)
    detail = acc.get("plan_detail") or {}
    retrieval = acc.get("retrieval_plan") or {}
    return _finish(
        acc,
        parts,
        {
            "change_type": (acc.get("ecr_analysis") or {}).get("change_type"),
            "investigations": detail.get("investigations", []),
            "skipped": detail.get("skipped", []),
            "search_terms": retrieval.get("search_terms", []),
            "reasoned_by": retrieval.get("source", "rules"),
        },
    )


@agent_step("gather_evidence", RETRIEVAL, "Gathering requirements, code impact, history, comments and evidence")
def gather_evidence(state: dict[str, Any]) -> dict[str, Any]:
    planned = set((state.get("plan_detail") or {}).get("investigations") or [])
    acc: dict[str, Any] = {}
    parts: list[dict[str, Any]] = []
    _part(state, acc, parts, "requirements", requirement_step, owner=RETRIEVAL)
    _part(state, acc, parts, "code_impact", code_impact_step, owner=RETRIEVAL)
    _part(state, acc, parts, "historical_defects", defect_step, owner=RETRIEVAL)
    if "dependencies" in planned:
        _part(state, acc, parts, "dependencies", dependency_step, owner=RETRIEVAL)
    _part(state, acc, parts, "collaboration_retrieval", collaboration_step, owner=RETRIEVAL)
    return _finish(
        acc,
        parts,
        {
            "requirements": len(acc.get("requirements") or []),
            "defects": len(acc.get("defects") or []),
            "comments": len(acc.get("comments") or []),
            "evidence": len(acc.get("evidence") or []),
        },
    )


@agent_step("assess_impact", CORRELATION, "Identifying impacted components")
def assess_impact(state: dict[str, Any]) -> dict[str, Any]:
    acc: dict[str, Any] = {}
    parts: list[dict[str, Any]] = []
    _part(state, acc, parts, "impact_assessment", impact_assessment_step, owner=CORRELATION, required=True)
    impact = acc.get("impact_analysis") or {}
    return _finish(
        acc,
        parts,
        {
            "direct": len(impact.get("directly_impacted_components") or []),
            "indirect": len(impact.get("indirectly_impacted_components") or []),
        },
    )


@agent_step("select_tests", CORRELATION, "Selecting regression tests, linking evidence and analysing related defects")
def select_tests(state: dict[str, Any]) -> dict[str, Any]:
    acc: dict[str, Any] = {}
    parts: list[dict[str, Any]] = []
    _part(state, acc, parts, "test_discovery", test_discovery_step, owner=CORRELATION)
    _part(state, acc, parts, "test_selection", test_selection_step, owner=CORRELATION)
    _part(state, acc, parts, "test_prioritization", test_prioritization_step, owner=CORRELATION)
    _part(state, acc, parts, "correlation", correlation_step, owner=CORRELATION)
    # Runs last: it checks each related defect against the tests selected above.
    _part(state, acc, parts, "defect_insights", defect_insights_step, owner=CORRELATION)
    # Last: the LLM reviews the whole correlated bundle, defect insights included.
    _part(state, acc, parts, "correlation_review", correlation_review_step, owner=CORRELATION)
    selection = acc.get("test_selection") or {}
    insights = acc.get("defect_insights") or {}
    review = acc.get("correlation_review") or {}
    return _finish(
        acc,
        parts,
        {
            "selected_tests": len(selection.get("selected_tests") or []),
            "defects_analysed": insights.get("total", 0),
            "defects_likely_to_return": insights.get("high", 0),
            "contradictions": len(review.get("conflicts") or []),
            "gaps": len(review.get("gaps") or []),
            "reasoned_by": review.get("source", "rules"),
        },
    )


@agent_step("summarize", SUMMARIZATION, "Writing the answer, the defect summary and the report", critical=True)
def summarize(state: dict[str, Any]) -> dict[str, Any]:
    acc: dict[str, Any] = {}
    parts: list[dict[str, Any]] = []
    # One LLM request writes both the answer and the defect summary.
    _part(state, acc, parts, "summarization", summarization_step, owner=SUMMARIZATION)
    _part(state, acc, parts, "report", report_step, owner=SUMMARIZATION, required=True)
    return _finish(acc, parts, {"citations": (acc.get("answer_citations") or [])[:12]})
