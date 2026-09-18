"""The three agents. There are no others.

    Retrieval Agent     -> LLM plans the search, gather the evidence
    Correlation Agent   -> assess the impact, select the regression tests,
                           LLM reviews the correlated sources for contradictions and gaps
    Summarization Agent -> LLM answers the user, publish the report

Each agent runs one or two of the five steps in :mod:`app.agents.nodes.steps`,
and each one reasons with the LLM (with a rule-based fallback when none is set).
A step is not an agent: it has no graph node of its own, it cannot route the
workflow, and it is labelled on the event stream with the agent that owns it.
"""
from __future__ import annotations

from typing import Any

from app.agents.nodes.steps import (
    assess_impact,
    gather_evidence,
    select_tests,
    summarize,
    understand_ecr,
)
from app.agents.runtime import agent_node, build_view, merge_partial


def _run(state: dict[str, Any], accumulated: dict[str, Any], step) -> dict[str, Any]:
    """Run one step against state + everything this agent produced so far."""
    return merge_partial(accumulated, step(build_view(state, accumulated)))


def _average(confidences: dict[str, float]) -> float:
    return round(sum(confidences.values()) / len(confidences), 3) if confidences else 0.6


@agent_node(
    "retrieval_agent",
    "Retrieval Agent",
    "Understanding the ECR and gathering its evidence",
    critical=True,
)
def retrieval_agent(state: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    result = _run(state, result, understand_ecr)
    result = _run(state, result, gather_evidence)

    sources = {
        "requirements": len(result.get("requirements") or []),
        "defects": len(result.get("defects") or []),
        "comments": len(result.get("comments") or []),
        "evidence": len(result.get("evidence") or []),
    }
    plan = result.get("retrieval_plan") or {}
    result["_confidence"] = _average(result.get("step_confidence") or {})
    result["_reasoning"] = (
        "Retrieved "
        + ", ".join(f"{value} {name}" for name, value in sources.items() if value)
        + f" for {state.get('ecr_id')}"
        + (
            f", searching with {len(plan.get('search_terms') or [])} LLM-planned term(s)."
            if plan.get("source") == "llm"
            else " with rule-based keywords (LLM unavailable)."
        )
    )
    result["_summary"] = {"sources": sources, "reasoned_by": plan.get("source", "rules")}
    return result


@agent_node(
    "correlation_agent",
    "Correlation Agent",
    "Assessing impact and selecting regression tests",
    critical=True,
)
def correlation_agent(state: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    result = _run(state, result, assess_impact)
    result = _run(state, result, select_tests)

    impact = result.get("impact_analysis") or {}
    selection = result.get("test_selection") or {}
    review = result.get("correlation_review") or {}
    result["_confidence"] = _average(result.get("step_confidence") or {})
    result["_reasoning"] = (
        f"{len(impact.get('directly_impacted_components') or [])} component(s) change directly; selected "
        f"{len(selection.get('selected_tests') or [])} of {selection.get('total_available')} tests. "
        f"{'LLM' if review.get('source') == 'llm' else 'Rule-based'} review found "
        f"{len(review.get('conflicts') or [])} contradiction(s) and {len(review.get('gaps') or [])} gap(s)."
    )
    result["_summary"] = {
        "direct_components": len(impact.get("directly_impacted_components") or []),
        "selected_tests": len(selection.get("selected_tests") or []),
        "contradictions": len(review.get("conflicts") or []),
        "gaps": len(review.get("gaps") or []),
        "reasoned_by": review.get("source", "rules"),
    }
    return result


@agent_node(
    "summarization_agent",
    "Summarization Agent",
    "Answering the question and publishing the report",
    critical=True,
)
def summarization_agent(state: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    result = _run(state, result, summarize)

    report = result.get("final_report") or {}
    result["_confidence"] = float((report.get("confidence") or {}).get("overall", 0.7))
    result["_reasoning"] = result.get("final_answer", "")[:400]
    result["_summary"] = {"citations": result.get("answer_citations", [])[:12]}
    return result


AGENTS = (retrieval_agent, correlation_agent, summarization_agent)
