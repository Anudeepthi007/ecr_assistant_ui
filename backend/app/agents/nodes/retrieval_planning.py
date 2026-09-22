"""Part of the *understand_ecr* step: the Retrieval Agent's LLM plans the search.

Rules only find what the ECR literally says. Before anything is fetched, the
model reads the change and names what else to look for - synonyms, the
behaviour that could break, related functions - and decides whether the dependency walk
is needed. Its search terms drive the requirement and defect searches in
*gather_evidence*, so the LLM changes what is retrieved, not just how it reads.

Guardrails: the model never supplies identifiers or scores. Its terms only
widen the semantic query (the relevance threshold still decides what is kept),
and it can only ask for *more* investigation, never skip one.
"""
from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, Field

from app.llm.provider import get_llm
from app.prompts import RETRIEVAL_SYSTEM_PROMPT, RETRIEVAL_TASK

MAX_TERMS = 10
MAX_BEHAVIOURS = 5
_IDENTIFIER = re.compile(r"[a-z]{1,6}-?\d[\w-]*")


class RetrievalPlan(BaseModel):
    summary: str = ""
    search_terms: list[str] = Field(default_factory=list)
    could_break: list[str] = Field(default_factory=list)
    needs_dependency_check: bool = False
    dependency_reason: str = ""
    source: str = "llm"


def _clean(values: list[str], limit: int) -> list[str]:
    """Short, lower-case, de-duplicated phrases; identifiers are not search terms."""
    kept: list[str] = []
    for value in values or []:
        term = " ".join(str(value).split()).strip(" .,;:").lower()[:60]
        if len(term) < 3 or _IDENTIFIER.fullmatch(term) or term in kept:
            continue
        kept.append(term)
    return kept[:limit]


def search_query(state: dict[str, Any]) -> str:
    """The query the evidence searches run: the ECR text plus the LLM's search terms."""
    ecr = state.get("ecr_input") or {}
    base = f"{ecr.get('title', '')}. {ecr.get('description', '')}"
    plan = state.get("retrieval_plan") or {}
    terms = plan.get("search_terms") or []
    if plan.get("source") != "llm" or not terms:
        return base
    return f"{base} Related: {'; '.join(terms)}."


def retrieval_planning_step(state: dict[str, Any]) -> dict[str, Any]:
    ecr = state["ecr_input"]
    analysis = dict(state.get("ecr_analysis") or {})
    fallback = {
        "summary": analysis.get("summary", ""),
        "search_terms": list(analysis.get("technical_keywords") or [])[:MAX_TERMS],
        "could_break": [],
        "needs_dependency_check": False,
        "dependency_reason": "",
        "source": "rules",
    }

    llm = get_llm()
    if llm.is_mock:
        plan = RetrievalPlan.model_validate(fallback)
    else:
        plan = llm.generate_structured(
            RETRIEVAL_TASK.format(
                ecr_id=ecr.get("ecr_id"),
                title=ecr.get("title"),
                description=ecr.get("description"),
                steps_to_reproduce=(ecr.get("steps_to_reproduce") or "").strip() or "not recorded",
                observed_behavior=(ecr.get("observed_behavior") or "").strip() or "not recorded",
                expected_behavior=(ecr.get("expected_behavior") or "").strip() or "not recorded",
                changed_files=json.dumps(ecr.get("changed_files") or []),
                linked_requirements=json.dumps(ecr.get("linked_requirements") or []),
                classification=json.dumps(
                    {
                        "change_type": analysis.get("change_type"),
                        "business_domain": analysis.get("business_domain"),
                        "keywords": analysis.get("technical_keywords"),
                        "candidate_components": analysis.get("candidate_components"),
                        "risk_indicators": analysis.get("risk_indicators"),
                    }
                ),
                max_terms=MAX_TERMS,
                max_behaviours=MAX_BEHAVIOURS,
            ),
            RetrievalPlan,
            system=RETRIEVAL_SYSTEM_PROMPT,
            fallback=fallback,
        )

    used_llm = plan.source != "rules"
    terms = _clean(plan.search_terms, MAX_TERMS)
    behaviours = _clean(plan.could_break, MAX_BEHAVIOURS)
    summary = " ".join(plan.summary.split()) or analysis.get("summary", "")
    wants_dependencies = used_llm and plan.needs_dependency_check

    if used_llm:
        reasoning = (
            f"The LLM planned the search with {len(terms)} term(s)"
            + (f" ({', '.join(terms[:4])})" if terms else "")
            + (f" and flagged {len(behaviours)} behaviour(s) that could break." if behaviours else ".")
            + (" It asked for the dependency walk." if wants_dependencies else "")
        )
    else:
        reasoning = "LLM unavailable, so the search uses the rule-based keywords only."

    return {
        # Only the language field changes; classification and numbers stay rule-based.
        "ecr_analysis": {**analysis, "summary": summary} if used_llm else analysis,
        "retrieval_plan": {
            "source": "llm" if used_llm else "rules",
            "summary": summary,
            "search_terms": terms,
            "could_break": behaviours,
            "needs_dependency_check": wants_dependencies,
            "dependency_reason": " ".join(plan.dependency_reason.split()) if wants_dependencies else "",
        },
        "tools_used": {"retrieval_planning": ["llm.plan_retrieval"] if used_llm else ["rule_keywords"]},
        "_reasoning": reasoning,
    }
