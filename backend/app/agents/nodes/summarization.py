"""Summarization steps: the plain answer, then the full report.

The answer is what replaces "read every comment and system by hand": it is
generated *only* from the correlated bundle, and it always ships with the
citations it was built from.
"""
from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from app.llm.provider import get_llm
from app.prompts import (
    ANSWER_SYSTEM_PROMPT,
    SUMMARY_DEFECT_INSTRUCTION,
    SUMMARY_NO_DEFECT_INSTRUCTION,
    SUMMARY_STYLE,
    SUMMARY_TASK,
)
from app.services.report_service import build_report

DEFAULT_QUESTION = (
    "What do I need to know about this change, and what should we test?"
)


def build_answer_context(state: dict[str, Any]) -> dict[str, Any]:
    """The grounded, citable context handed to the model (and to the API)."""
    impact = state.get("impact_analysis") or {}
    selection = state.get("test_selection") or {}
    collaboration = state.get("collaboration_analysis") or {}
    signals = collaboration.get("signals") or {}
    review = state.get("correlation_review") or {}
    return {
        "ecr": {
            "id": state.get("ecr_id"),
            "title": (state.get("ecr_input") or {}).get("title"),
            "description": (state.get("ecr_input") or {}).get("description"),
            "change_type": (state.get("ecr_analysis") or {}).get("change_type"),
            "business_domain": (state.get("ecr_analysis") or {}).get("business_domain"),
        },
        "requirements": [
            {
                "id": r["requirement_id"],
                "title": r["title"],
                "relevance": r["relevance"],
                "why": r["reason"],
            }
            for r in (state.get("requirements") or [])[:8]
        ],
        "historical_defects": _defect_context(state),
        "decisions": [
            {"by": item["author"], "text": item["text"], "ref": item["comment_id"]}
            for item in signals.get("decisions", [])[:5]
        ],
        "raised_concerns": [
            {"by": item["author"], "text": item["text"], "ref": item["comment_id"]}
            for item in signals.get("risks", [])[:5]
        ],
        "evidence": [
            {
                "id": e["evidence_id"],
                "title": e["title"],
                "type": e["evidence_type"],
                "outcome": e["outcome"],
            }
            for e in (state.get("evidence") or [])[:6]
        ],
        "evidence_gaps": collaboration.get("evidence_gaps", []),
        # What the other two agents' LLM reasoning concluded.
        "could_break": (state.get("retrieval_plan") or {}).get("could_break", []),
        "correlation_findings": {
            "summary": review.get("summary", ""),
            "contradictions": review.get("conflicts", []),
            "gaps": review.get("gaps", []),
            "key_links": review.get("key_links", []),
        },
        "impact_summary": {
            "direct_components": len(impact.get("directly_impacted_components") or []),
            "indirect_components": len(impact.get("indirectly_impacted_components") or []),
        },
        "human_approval": _approval_context(state),
        "impacted_components": [
            {"id": c["component_id"], "name": c["name"], "impact": c["impact_type"]}
            for c in [
                *(impact.get("directly_impacted_components") or []),
                *(impact.get("indirectly_impacted_components") or []),
            ][:10]
        ],
        "tests": {
            "total_available": selection.get("total_available"),
            "recommended": len(selection.get("selected_tests") or []),
            "reduction_percentage": selection.get("reduction_percentage"),
            "priority_distribution": selection.get("priority_distribution"),
            "top": [
                {
                    "id": t["test_case_id"],
                    "title": t["title"],
                    "priority": t["priority"],
                    "relevance": t["relevance_score"],
                    "why": t["reason"],
                }
                for t in (selection.get("selected_tests") or [])[:8]
            ],
        },
    }


def _defect_context(state: dict[str, Any]) -> list[dict[str, Any]]:
    analysed = {row["defect_id"]: row for row in (state.get("defect_insights") or {}).get("defects") or []}
    out = []
    for d in (state.get("defects") or [])[:6]:
        row = analysed.get(d["defect_id"], {})
        out.append(
            {
                "id": d["defect_id"],
                "title": d["title"],
                "severity": d["severity"],
                "root_cause": d["root_cause"],
                "why": row.get("why_it_matters") or d["reason"],
                "chance_it_happens_again": row.get("chance_of_recurrence"),
                "covered_by_tests": row.get("covering_tests", []),
            }
        )
    return out


def _baseline_answer(context: dict[str, Any]) -> str:
    ecr = context["ecr"]
    impact = context["impact_summary"]
    tests = context["tests"]
    parts = [
        f"{ecr['id']} ({ecr['title']}) is a "
        f"{str(ecr.get('change_type') or 'change').replace('_', ' ').lower()} in the "
        f"{ecr.get('business_domain')} domain. It changes {impact['direct_components']} "
        f"component(s) directly and reaches {impact['indirect_components']} more through "
        f"dependencies."
    ]
    if context["requirements"]:
        parts.append(
            "It touches "
            + ", ".join(f"{r['id']} ({r['title']})" for r in context["requirements"][:3])
            + "."
        )
    if context["historical_defects"]:
        parts.append(
            "History is relevant here: "
            + ", ".join(
                f"{d['id']} ({d['title']})" for d in context["historical_defects"][:3]
            )
            + "."
        )
    if context["decisions"]:
        parts.append("Decisions already recorded: " + context["decisions"][0]["text"])
    if context["raised_concerns"]:
        parts.append("Open concern: " + context["raised_concerns"][0]["text"])
    contradictions = context["correlation_findings"]["contradictions"]
    if contradictions:
        parts.append("To resolve: " + contradictions[0]["text"])
    if tests.get("recommended"):
        distribution = tests.get("priority_distribution") or {}
        parts.append(
            f"Recommended regression: {tests['recommended']} of {tests['total_available']} tests "
            f"({tests['reduction_percentage']}% reduction), "
            f"{distribution.get('P0', 0)} P0 and {distribution.get('P1', 0)} P1."
        )
    if context["evidence_gaps"]:
        parts.append(
            "Evidence is missing for: " + ", ".join(context["evidence_gaps"][:4]) + "."
        )
    approval_sentence = _approval_sentence(context.get("human_approval") or {})
    if approval_sentence:
        parts.append(approval_sentence)
    return " ".join(parts)


def _approval_context(state: dict[str, Any]) -> dict[str, Any]:
    """Whether a person was asked to approve this analysis, and what they decided."""
    approval = state.get("approval") or {}
    if not approval.get("required"):
        return {"requested": False}
    return {
        "requested": True,
        "status": approval.get("status", ""),
        "decided_by": approval.get("decided_by", ""),
        "comment": approval.get("comment", ""),
        "excluded_tests": approval.get("excluded_test_ids", []),
    }


def _approval_sentence(approval: dict[str, Any]) -> str:
    if not approval.get("requested"):
        return ""
    who = approval.get("decided_by") or "The reviewer"
    status = approval.get("status")
    if status == "APPROVED":
        excluded = approval.get("excluded_tests") or []
        return f"{who} approved this analysis" + (
            f" and removed {', '.join(excluded)} from the recommendation." if excluded else "."
        )
    if status == "REJECTED":
        return f"{who} rejected this analysis, so the test recommendation is on hold."
    if status == "TIMED_OUT":
        return "Approval was requested but no decision arrived in time."
    return ""


class SummaryReply(BaseModel):
    """The Summarization Agent's one LLM reply: the answer and the defect summary together."""

    answer: str = ""
    defect_summary: str = ""


def _baseline_defect_summary(ecr_id: str, insights: dict[str, Any]) -> str:
    rows = insights.get("defects") or []
    history = insights.get("component_history") or []
    open_now = insights.get("open_defects") or []
    open_sentence = (
        "Still open in the affected area: "
        + "; ".join(f"{d['defect_id']} ({d['title']}, {d['severity'].lower()})" for d in open_now[:3])
        + "."
        if open_now
        else ""
    )
    if not rows:
        if not history:
            if insights.get("scoped"):
                return f"No past defects are linked to the requirements or test cases of {ecr_id}." + (
                    f" {open_sentence}" if open_sentence else ""
                )
            return f"No defects are recorded for {ecr_id} or the components it touches." + (
                f" {open_sentence}" if open_sentence else ""
            )
        total = sum(h["total"] for h in history)
        latest = min(
            (h for h in history if h["last_seen_days"] is not None),
            key=lambda h: h["last_seen_days"],
            default=history[0],
        )
        busiest = max(history, key=lambda h: h["total"])
        parts = [
            f"No past defect matches {ecr_id} directly, but the components it touches have "
            f"{total} recorded defect(s)."
        ]
        if latest["last_seen_days"] is not None:
            parts.append(f"The most recent was {latest['last_seen_days']} days ago on {latest['component_name']}.")
        if busiest["top_cause"]:
            parts.append(
                f"{busiest['component_name']} has the most ({busiest['total']}), usually caused by "
                f"{busiest['top_cause'][:1].lower() + busiest['top_cause'][1:]}."
            )
        if open_sentence:
            parts.append(open_sentence)
        return " ".join(parts)
    parts = [f"{len(rows)} past defect(s) are related to {ecr_id}."]
    high = [row for row in rows if row["chance_of_recurrence"] == "High"]
    medium = [row for row in rows if row["chance_of_recurrence"] == "Medium"]
    if high:
        parts.append(
            "These could happen again with this change: "
            + "; ".join(f"{row['defect_id']} ({row['title']})" for row in high[:3])
            + "."
        )
    elif medium:
        parts.append(
            "None is likely to come back, but keep an eye on "
            + ", ".join(row["defect_id"] for row in medium[:3])
            + "."
        )
    else:
        parts.append("None of them is likely to happen again, because this change does not touch their code.")
    # Lower-case the first letter only, and never an acronym ("UI error handling").
    causes = [
        cause if cause[:2].isupper() else cause[:1].lower() + cause[1:]
        for cause in (insights.get("common_causes") or [])[:2]
    ]
    if causes and (high or medium):
        parts.append(
            ("The most common causes were " if len(causes) > 1 else "The most common cause was ")
            + " and ".join(causes)
            + "."
        )
    uncovered = insights.get("not_covered") or []
    if uncovered:
        verb = "is" if len(uncovered) == 1 else "are"
        parts.append(
            f"{', '.join(uncovered[:4])} {verb} not covered by the recommended tests, so check "
            f"{'it' if len(uncovered) == 1 else 'them'} manually."
        )
    elif high or medium:
        parts.append("The recommended tests cover every defect that could come back.")
    if open_sentence:
        parts.append(open_sentence)
    return " ".join(parts)


def summarization_step(state: dict[str, Any]) -> dict[str, Any]:
    """The Summarization Agent's single LLM request: the answer and the defect summary in one reply."""
    options = state.get("options") or {}
    question = (options.get("question") or "").strip() or DEFAULT_QUESTION
    ecr_id = state.get("ecr_id", "this ECR")
    context = build_answer_context(state)
    insights = state.get("defect_insights") or {}
    baseline = _baseline_answer(context)
    defect_baseline = _baseline_defect_summary(ecr_id, insights)
    # Matched defects are rewritten by the model; a history-only summary stays factual.
    rewrite_defects = bool(insights.get("defects"))

    answer, defect_summary, used_llm = baseline, defect_baseline, False
    llm = get_llm()
    if not llm.is_mock:
        reply = llm.generate_structured(
            SUMMARY_TASK.format(
                question=question,
                bundle=json.dumps(context, default=str)[:14000],
                defect_instruction=(
                    SUMMARY_DEFECT_INSTRUCTION.format(ecr_id=ecr_id)
                    if rewrite_defects
                    else SUMMARY_NO_DEFECT_INSTRUCTION
                ),
            ),
            SummaryReply,
            system=ANSWER_SYSTEM_PROMPT + SUMMARY_STYLE,
            fallback={"answer": baseline, "defect_summary": defect_baseline},
            temperature=0.2,
            # The fast model, like the other two agents: the main model took longer
            # than the request timeout on this bundle, and a timed-out request is
            # billed but its answer is lost.
            fast=True,
        )
        answer = reply.answer.strip() or baseline
        if rewrite_defects:
            defect_summary = reply.defect_summary.strip() or defect_baseline
        used_llm = answer != baseline

    citations = sorted(
        {
            *(r["id"] for r in context["requirements"]),
            *(d["id"] for d in context["historical_defects"]),
            *(t["id"] for t in context["tests"]["top"]),
            *(item["ref"] for item in context["decisions"]),
            *(item["ref"] for item in context["raised_concerns"]),
            *(e["id"] for e in context["evidence"]),
        }
    )
    confidence = round(min(0.95, 0.55 + 0.05 * min(8, len(citations))), 3)
    return {
        "final_answer": answer,
        "answer_context": context,
        "answer_citations": citations,
        "question": question,
        "defect_summary": defect_summary,
        "tools_used": {
            "summarization": ["build_answer_context", "llm.summarize" if used_llm else "rule_summary"]
        },
        "_confidence": confidence,
        "_reasoning": baseline,
    }


def report_step(state: dict[str, Any]) -> dict[str, Any]:
    report = build_report(state)
    return {
        "final_report": report.model_dump(mode="json"),
        "tools_used": {"report": ["report_service.build"]},
        "_confidence": report.confidence.overall,
        "_reasoning": (
            f"Assembled {len(report.sections)} report sections with overall confidence "
            f"{report.confidence.overall:.0%} ({report.confidence.band.value})."
        ),
        "_summary": {
            "sections": len(report.sections),
            "confidence": report.confidence.overall,
            "metrics": report.metrics,
        },
    }
