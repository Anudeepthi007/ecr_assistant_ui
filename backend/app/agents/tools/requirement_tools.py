"""Tools of the Requirement Intelligence Agent."""
from __future__ import annotations

import re
from typing import Any, Iterable

from sqlalchemy.orm import Session

from app.agents.tools.registry import tool
from app.repositories import RequirementRepository
from app.services.rag_service import get_rag_service
from app.vectorstore import COLLECTION_REQUIREMENTS


@tool("semantic_requirement_search", "Vector + keyword hybrid search over the requirement corpus.")
def semantic_requirement_search(
    query: str, *, keywords: Iterable[str] = (), k: int = 12
) -> list[dict[str, Any]]:
    documents = get_rag_service().retrieve(
        COLLECTION_REQUIREMENTS, query, k=k, keywords=keywords, min_relevance=20
    )
    return [
        {**doc.metadata, "relevance": doc.relevance, "match_type": "SEMANTIC",
         "dense": doc.dense_score, "lexical": doc.lexical_score}
        for doc in documents
    ]


@tool("keyword_requirement_search", "Literal keyword match across requirement titles and text.")
def keyword_requirement_search(
    db: Session, keywords: Iterable[str], *, limit: int = 12
) -> list[dict[str, Any]]:
    terms = [k.lower() for k in keywords if len(k) > 2]
    if not terms:
        return []
    results: list[dict[str, Any]] = []
    for requirement in RequirementRepository(db).list():
        haystack = f"{requirement.title} {requirement.description} {' '.join(requirement.features or [])}".lower()
        hits = [term for term in terms if term in haystack]
        if not hits:
            continue
        payload = requirement.as_dict()
        payload["relevance"] = round(min(100.0, 45 + 18 * len(hits)), 1)
        payload["match_type"] = "KEYWORD"
        payload["matched_terms"] = hits
        results.append(payload)
    results.sort(key=lambda item: item["relevance"], reverse=True)
    return results[:limit]


# An explicit ECR -> requirement link is near-certain, so every traced requirement
# starts high. It is not, however, a measure of how much of the change lands on that
# requirement - and a flat 100 for every link made the list unrankable. The spread
# above the base is earned from signals the change record itself carries.
TRACE_BASE = 82.0
TRACE_SPREAD = 18.0
COMPONENT_LINK_RELEVANCE = 78.0

_WORD = re.compile(r"[a-z0-9]+")
_STOPWORDS = {
    "shall", "when", "with", "that", "this", "from", "into", "onto", "than", "then",
    "they", "them", "there", "their", "which", "while", "would", "could", "should",
    "been", "being", "have", "must", "only", "also", "each", "such", "does", "made",
    "make", "used", "using", "onboard", "segment", "system", "test", "tests",
}


def _terms(*parts: Any) -> set[str]:
    """Content words of a piece of text, for cheap lexical overlap."""
    blob = " ".join(str(p) for p in parts if p).lower()
    return {w for w in _WORD.findall(blob) if len(w) > 3 and w not in _STOPWORDS}


def _named_test_counts(ecr: dict[str, Any] | None) -> dict[str, int]:
    """How many of the ECR's affected test cases belong to each requirement.

    Affected test cases are written "L2R26: TC2", so the part before the colon
    names the requirement the change was actually observed against.
    """
    counts: dict[str, int] = {}
    for value in (ecr or {}).get("affected_test_cases") or []:
        test_id = "".join(str(value).split())
        if ":" not in test_id:
            continue
        requirement_id = test_id.split(":", 1)[0]
        counts[requirement_id] = counts.get(requirement_id, 0) + 1
    return counts


@tool("trace_requirements", "Follow explicit ECR -> requirement and component -> requirement links.")
def trace_requirements(
    db: Session,
    requirement_ids: Iterable[str],
    component_ids: Iterable[str],
    *,
    ecr: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    repository = RequirementRepository(db)
    found: dict[str, dict[str, Any]] = {}

    traced = list(repository.get_many(list(requirement_ids)))
    test_counts = _named_test_counts(ecr)
    ecr_terms = _terms(
        (ecr or {}).get("title"),
        (ecr or {}).get("description"),
        (ecr or {}).get("steps_to_reproduce"),
        (ecr or {}).get("observed_behavior"),
        (ecr or {}).get("expected_behavior"),
    )
    overlaps = {
        r.requirement_id: len(
            ecr_terms & _terms(r.title, r.description, " ".join(r.features or []))
        )
        for r in traced
    }
    # Both signals are scored relative to the strongest linked requirement, so the
    # list ranks even when the change record names only a handful of requirements.
    top_tests = max((test_counts.get(r.requirement_id, 0) for r in traced), default=0)
    top_overlap = max(overlaps.values(), default=0)
    # Weight whichever signals this change record actually carries.
    weights = [(0.6 if top_tests else 0.0), (0.4 if top_overlap else 0.0)]
    total_weight = sum(weights) or 1.0

    for requirement in traced:
        rid = requirement.requirement_id
        test_share = (test_counts.get(rid, 0) / top_tests) if top_tests else 0.0
        overlap_share = (overlaps.get(rid, 0) / top_overlap) if top_overlap else 0.0
        earned = (weights[0] * test_share + weights[1] * overlap_share) / total_weight
        payload = requirement.as_dict()
        payload["relevance"] = round(min(100.0, TRACE_BASE + TRACE_SPREAD * earned), 1)
        payload["match_type"] = "TRACEABILITY"
        payload["named_test_count"] = test_counts.get(rid, 0)
        found[rid] = payload

    for component_id in component_ids:
        for requirement in repository.by_component(component_id):
            if requirement.requirement_id in found:
                continue
            payload = requirement.as_dict()
            payload["relevance"] = COMPONENT_LINK_RELEVANCE
            payload["match_type"] = "COMPONENT_LINK"
            found[requirement.requirement_id] = payload
    return list(found.values())
