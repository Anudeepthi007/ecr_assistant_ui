"""Retrieval Agent step: impacted requirements.

Three retrieval channels are fused so an identifier-heavy enterprise corpus is
not left to dense similarity alone:
  1. explicit traceability (ECR -> requirement links, component -> requirement),
  2. hybrid semantic search over the requirement corpus,
  3. literal keyword search.
"""
from __future__ import annotations

from typing import Any

from app.agents.nodes.retrieval_planning import search_query
from app.agents.tools.requirement_tools import (
    keyword_requirement_search,
    semantic_requirement_search,
    trace_requirements,
)
from app.agents.nodes.scope import is_scoped, linked_requirement_ids
from app.database import session_scope
from app.llm.provider import get_llm
from app.models import Requirement
from app.schemas.impact import RequirementAnalysis, RequirementMatch

MATCH_WEIGHT = {"TRACEABILITY": 1.0, "COMPONENT_LINK": 0.85, "SEMANTIC": 0.9, "KEYWORD": 0.8}
MIN_RELEVANCE = 45.0
MAX_MATCHES = 10


def requirement_step(state: dict[str, Any]) -> dict[str, Any]:
    ecr = state["ecr_input"]
    analysis = state.get("ecr_analysis") or {}
    keywords = analysis.get("technical_keywords") or []
    query = search_query(state)  # widened by the Retrieval Agent's LLM search plan

    scoped = is_scoped(ecr)
    with session_scope() as db:
        traced = trace_requirements(
            db,
            ecr.get("linked_requirements") or [],
            analysis.get("candidate_components") or [],
            ecr=ecr,
        )
        keyword_hits = [] if scoped else keyword_requirement_search(db, keywords)
        searched_total = db.query(Requirement).count()
    semantic_hits = [] if scoped else semantic_requirement_search(query, keywords=keywords, k=12)
    if scoped:  # only the requirements the change record itself links
        wanted = linked_requirement_ids(ecr)
        traced = [payload for payload in traced if payload.get("requirement_id") in wanted]

    merged: dict[str, dict[str, Any]] = {}
    for payload in [*traced, *semantic_hits, *keyword_hits]:
        requirement_id = payload.get("requirement_id")
        if not requirement_id:
            continue
        candidate = dict(payload)
        candidate["relevance"] = round(
            float(payload.get("relevance", 0.0))
            * MATCH_WEIGHT.get(payload.get("match_type", "SEMANTIC"), 0.8),
            1,
        )
        existing = merged.get(requirement_id)
        if existing is None:
            merged[requirement_id] = candidate
            continue
        # a requirement found through several channels is more certain
        best, other = (
            (existing, candidate)
            if existing["relevance"] >= candidate["relevance"]
            else (candidate, existing)
        )
        best = dict(best)
        best["relevance"] = round(min(100.0, best["relevance"] + 0.25 * other["relevance"]), 1)
        best["match_type"] = f"{best.get('match_type')}+{other.get('match_type')}"
        merged[requirement_id] = best

    matches: list[RequirementMatch] = []
    for payload in merged.values():
        if payload["relevance"] < MIN_RELEVANCE:
            continue
        matches.append(
            RequirementMatch(
                requirement_id=payload["requirement_id"],
                title=payload.get("title", ""),
                description=payload.get("description", ""),
                business_domain=payload.get("business_domain", ""),
                priority=payload.get("priority", "MEDIUM"),
                component=payload.get("component", ""),
                linked_components=list(payload.get("linked_components") or []),
                features=list(payload.get("features") or []),
                relevance=payload["relevance"],
                match_type=payload.get("match_type", "SEMANTIC"),
                reason=_reason(payload),
            )
        )
    matches.sort(key=lambda m: m.relevance, reverse=True)
    matches = matches[:MAX_MATCHES]

    impacted_components = sorted(
        {c for match in matches for c in [match.component, *match.linked_components] if c}
    )
    confidence = _confidence(matches)
    baseline = (
        (
            f"Used the {len(matches)} requirement(s) linked to this ECR in its change record. Strongest "
            f"match is {matches[0].requirement_id} ({matches[0].title}) at {matches[0].relevance:.0f}% relevance."
            if matches
            else "No requirement is linked to this ECR in its change record."
        )
        if scoped
        else f"Searched {searched_total} requirements across traceability, semantic and keyword "
        f"channels and matched {len(matches)}. Strongest match is "
        f"{matches[0].requirement_id} ({matches[0].title}) at {matches[0].relevance:.0f}% relevance."
        if matches
        else f"Searched {searched_total} requirements and found no match above the {MIN_RELEVANCE:.0f}% threshold."
    )
    reasoning = get_llm().narrate(
        task="Explain which requirements are impacted by this change and why",
        context={
            "ecr": ecr.get("ecr_id"),
            "matches": [
                {"id": m.requirement_id, "title": m.title, "relevance": m.relevance, "via": m.match_type}
                for m in matches[:5]
            ],
        },
        fallback=baseline,
    )

    result = RequirementAnalysis(
        matched_requirements=matches,
        impacted_components=impacted_components,
        searched_count=searched_total,
        confidence=confidence,
        reasoning=reasoning,
    )
    return {
        "requirements": [m.model_dump(mode="json") for m in matches],
        "requirement_analysis": result.model_dump(mode="json"),
        "tools_used": {
            "requirements": [
                "trace_requirements",
                "semantic_requirement_search",
                "keyword_requirement_search",
            ]
        },
        "_confidence": confidence,
        "_reasoning": reasoning,
        "_summary": {
            "matched": len(matches),
            "searched": searched_total,
            "top": [m.requirement_id for m in matches[:5]],
        },
    }


def _reason(payload: dict[str, Any]) -> str:
    match_type = payload.get("match_type", "SEMANTIC")
    if "TRACEABILITY" in match_type:
        named = payload.get("named_test_count") or 0
        if named:
            return (
                f"Explicitly linked to the ECR in the change record, which names "
                f"{named} of its test case(s) as affected."
            )
        return "Explicitly linked to the ECR in the change record."
    if "COMPONENT_LINK" in match_type:
        return f"Traced through component {payload.get('component')} identified in the change."
    if "KEYWORD" in match_type:
        terms = payload.get("matched_terms") or []
        return f"Literal match on change keywords: {', '.join(terms[:4])}."
    return "Strong semantic similarity between the change description and the requirement text."


def _confidence(matches: list[RequirementMatch]) -> float:
    if not matches:
        return 0.35
    top = matches[0].relevance / 100.0
    breadth = min(1.0, len(matches) / 5.0)
    traced = any("TRACEABILITY" in m.match_type for m in matches)
    return round(min(0.97, 0.45 + 0.35 * top + 0.12 * breadth + (0.08 if traced else 0.0)), 3)
