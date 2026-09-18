"""Tools of the Defect Intelligence Agent."""
from __future__ import annotations

from collections import Counter
from typing import Any, Iterable

from sqlalchemy.orm import Session

from app.agents.tools.registry import tool
from app.repositories import DefectRepository
from app.services.rag_service import get_rag_service
from app.vectorstore import COLLECTION_DEFECTS


@tool("semantic_defect_search", "Hybrid search over historical defects and incident write-ups.")
def semantic_defect_search(
    query: str, *, keywords: Iterable[str] = (), k: int = 12
) -> list[dict[str, Any]]:
    documents = get_rag_service().retrieve(
        COLLECTION_DEFECTS, query, k=k, keywords=keywords, min_relevance=20
    )
    return [{**doc.metadata, "similarity": doc.relevance} for doc in documents]


@tool("defects_by_component", "Retrieve every defect recorded against the impacted components.")
def defects_by_component(db: Session, component_ids: Iterable[str]) -> list[dict[str, Any]]:
    components = list(component_ids)
    results = []
    for defect in DefectRepository(db).by_components(components):
        payload = defect.as_dict()
        payload["similarity"] = 70.0 if defect.affected_component in components else 55.0
        results.append(payload)
    return results


@tool("cluster_root_causes", "Group defects by root-cause category to expose recurring patterns.")
def cluster_root_causes(defects: list[dict[str, Any]]) -> list[str]:
    counter = Counter(
        defect.get("root_cause_category", "").strip()
        for defect in defects
        if defect.get("root_cause_category")
    )
    patterns = []
    for category, count in counter.most_common(5):
        if count >= 2:
            patterns.append(f"{category} ({count} occurrences)")
        elif counter.total() <= 3:
            patterns.append(category)
    return patterns


