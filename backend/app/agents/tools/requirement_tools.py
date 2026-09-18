"""Tools of the Requirement Intelligence Agent."""
from __future__ import annotations

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


@tool("trace_requirements", "Follow explicit ECR -> requirement and component -> requirement links.")
def trace_requirements(
    db: Session, requirement_ids: Iterable[str], component_ids: Iterable[str]
) -> list[dict[str, Any]]:
    repository = RequirementRepository(db)
    found: dict[str, dict[str, Any]] = {}
    for requirement in repository.get_many(list(requirement_ids)):
        payload = requirement.as_dict()
        payload["relevance"] = 100.0
        payload["match_type"] = "TRACEABILITY"
        found[requirement.requirement_id] = payload
    for component_id in component_ids:
        for requirement in repository.by_component(component_id):
            if requirement.requirement_id in found:
                continue
            payload = requirement.as_dict()
            payload["relevance"] = 78.0
            payload["match_type"] = "COMPONENT_LINK"
            found[requirement.requirement_id] = payload
    return list(found.values())
