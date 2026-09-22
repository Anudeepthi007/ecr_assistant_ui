"""Retrieval Agent step: similar historical defects.

Answers "has a change like this hurt us before?" by fusing semantic similarity
over incident write-ups with component-scoped defect history, then clustering
root causes into recurring patterns.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from app.agents.nodes.retrieval_planning import search_query
from app.agents.tools.defect_tools import (
    cluster_root_causes,
    defects_by_component,
    semantic_defect_search,
)
from app.agents.nodes.scope import is_scoped, linked_requirement_ids
from app.database import session_scope
from app.llm.provider import get_llm
from app.models import Defect
from app.schemas.impact import DefectAnalysis, DefectMatch

MIN_SIMILARITY = 40.0
MAX_DEFECTS = 10


def defect_step(state: dict[str, Any]) -> dict[str, Any]:
    ecr = state["ecr_input"]
    analysis = state.get("ecr_analysis") or {}
    code_impact = state.get("code_impact") or {}
    requirement_analysis = state.get("requirement_analysis") or {}

    components = sorted(
        {
            *(code_impact.get("impacted_services") or []),
            *(code_impact.get("potentially_impacted_services") or []),
            *(requirement_analysis.get("impacted_components") or []),
            *(analysis.get("candidate_components") or []),
        }
    )
    query = search_query(state)  # widened by the Retrieval Agent's LLM search plan
    keywords = analysis.get("technical_keywords") or []

    scoped = is_scoped(ecr)
    semantic_hits = [] if scoped else semantic_defect_search(query, keywords=keywords, k=14)
    with session_scope() as db:
        if scoped:  # only defects raised against the requirements the record links
            wanted = linked_requirement_ids(ecr)
            component_hits = [
                {**row.as_dict(), "similarity": 90.0}
                for row in db.query(Defect).all()
                if wanted & set(row.linked_requirements or [])
            ]
        else:
            component_hits = defects_by_component(db, components)
        searched_total = db.query(Defect).count()

    merged: dict[str, dict[str, Any]] = {}
    for payload in [*semantic_hits, *component_hits]:
        defect_id = payload.get("defect_id")
        if not defect_id:
            continue
        existing = merged.get(defect_id)
        if existing is None:
            merged[defect_id] = dict(payload)
            continue
        # found through both channels -> stronger evidence
        best = dict(existing if existing["similarity"] >= payload["similarity"] else payload)
        best["similarity"] = round(
            min(100.0, max(existing["similarity"], payload["similarity"]) + 12.0), 1
        )
        merged[defect_id] = best

    # Traceability beats text similarity: a defect raised against a requirement this
    # ECR changes is relevant even when older, wordier defects look more similar.
    ecr_requirements = set(ecr.get("linked_requirements") or [])
    matched_requirements = {r["requirement_id"] for r in state.get("requirements") or []}
    for payload in merged.values():
        linked = set(payload.get("linked_requirements") or [])
        if linked & ecr_requirements:
            payload["similarity"] = round(min(100.0, payload["similarity"] + 15.0), 1)
        elif linked & matched_requirements:
            payload["similarity"] = round(min(100.0, payload["similarity"] + 6.0), 1)

    candidates = [d for d in merged.values() if d["similarity"] >= MIN_SIMILARITY]
    candidates.sort(key=lambda d: d["similarity"], reverse=True)
    candidates = candidates[:MAX_DEFECTS]

    matches = [
        DefectMatch(
            defect_id=d["defect_id"],
            title=d.get("title", ""),
            severity=d.get("severity", "MEDIUM"),
            status=d.get("status", "CLOSED"),
            root_cause=d.get("root_cause", ""),
            root_cause_category=d.get("root_cause_category", ""),
            affected_component=d.get("affected_component", ""),
            similarity=d["similarity"],
            escaped_to_production=bool(d.get("escaped_to_production")),
            reason=_reason(d, components, ecr_requirements),
        )
        for d in candidates
    ]

    patterns = cluster_root_causes(candidates)
    severity_distribution = dict(Counter(m.severity for m in matches))
    component_counter = Counter(m.affected_component for m in matches if m.affected_component)
    defect_prone_components = [comp for comp, count in component_counter.most_common(5) if count >= 1]

    confidence = round(
        min(0.95, 0.4 + 0.3 * min(1.0, len(matches) / 5.0) + 0.2 * bool(components) + 0.05),
        3,
    )
    baseline = (
        (
            f"Checked the past defects linked to this ECR's own requirements and found {len(matches)}. "
            if scoped
            else f"Searched {searched_total} historical defects and found {len(matches)} related to this change. "
        )
        + (
            f"Recurring patterns: {'; '.join(patterns)}. "
            if patterns
            else "No recurring root-cause pattern emerged. "
        )
        + (
            f"Components with the most related defects: {', '.join(defect_prone_components[:3])}."
            if defect_prone_components
            else "No component concentration detected."
        )
    )
    reasoning = get_llm().narrate(
        task="Explain what past defects tell us about this change",
        context={
            "defects": [
                {"id": m.defect_id, "title": m.title, "severity": m.severity, "similarity": m.similarity}
                for m in matches[:6]
            ],
            "patterns": patterns,
        },
        fallback=baseline,
    )

    result = DefectAnalysis(
        similar_defects=matches,
        defect_prone_components=defect_prone_components,
        recurring_failure_patterns=patterns,
        severity_distribution=severity_distribution,
        searched_count=searched_total,
        confidence=confidence,
        reasoning=reasoning,
    )
    return {
        "defects": [m.model_dump(mode="json") for m in matches],
        "defect_analysis": result.model_dump(mode="json"),
        "tools_used": {
            "historical_defects": [
                "semantic_defect_search",
                "defects_by_component",
                "cluster_root_causes",
            ]
        },
        "_confidence": confidence,
        "_reasoning": reasoning,
        "_summary": {
            "matched": len(matches),
            "searched": searched_total,
            "patterns": patterns,
        },
    }


def _reason(defect: dict[str, Any], components: list[str], ecr_requirements: set[str]) -> str:
    parts = []
    shared = sorted(set(defect.get("linked_requirements") or []) & ecr_requirements)
    if shared:
        parts.append(f"linked to {', '.join(shared)}, which this ECR changes")
    if defect.get("affected_component") in components:
        parts.append(f"same component ({defect['affected_component']}) as the current change")
    if defect.get("root_cause_category"):
        parts.append(f"root cause '{defect['root_cause_category']}'")
    if defect.get("escaped_to_production"):
        parts.append("escaped to production")
    if defect.get("reopen_count"):
        parts.append(f"reopened {defect['reopen_count']} time(s)")
    if not parts:
        return "Textually similar to the change description."
    return "Matched on " + "; ".join(parts) + "."
