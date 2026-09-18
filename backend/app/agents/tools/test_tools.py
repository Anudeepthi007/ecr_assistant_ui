"""Tools of the Test Discovery / Selection / Prioritisation agents."""
from __future__ import annotations

from typing import Any, Iterable

from sqlalchemy.orm import Session

from app.agents.tools.registry import tool
from app.repositories import TestRepository
from app.services.rag_service import get_rag_service
from app.vectorstore import COLLECTION_TESTS


@tool("tests_by_requirement", "Fetch every test traced to the impacted requirements.")
def tests_by_requirement(db: Session, requirement_ids: Iterable[str]) -> list[dict[str, Any]]:
    return [t.as_dict() for t in TestRepository(db).by_requirements(list(requirement_ids))]


@tool("tests_by_component", "Fetch every test covering the impacted components.")
def tests_by_component(db: Session, component_ids: Iterable[str]) -> list[dict[str, Any]]:
    return [t.as_dict() for t in TestRepository(db).by_components(list(component_ids))]


@tool("semantic_test_search", "Hybrid semantic search over the test catalogue.")
def semantic_test_search(
    query: str, *, keywords: Iterable[str] = (), k: int = 60
) -> list[dict[str, Any]]:
    documents = get_rag_service().retrieve(
        COLLECTION_TESTS, query, k=k, keywords=keywords, min_relevance=15
    )
    return [{**doc.metadata, "semantic_score": doc.relevance} for doc in documents]


@tool("total_test_inventory", "Size of the regression suite that is the optimisation baseline.")
def total_test_inventory(db: Session, domain: str | None = None) -> int:
    """Baseline = the suite a team would otherwise run.

    Scoped to the ECR's own domain: a payments change would never trigger the
    rail suite, so counting it would inflate the reduction figure.
    """
    rows = TestRepository(db).list()
    return sum(1 for t in rows if not t.retired and (domain is None or t.domain == domain))


@tool("baseline_duration", "Execution time of the baseline regression suite in minutes.")
def baseline_duration(db: Session, domain: str | None = None) -> float:
    rows = TestRepository(db).list()
    total = sum(
        t.average_execution_time
        for t in rows
        if not t.retired and (domain is None or t.domain == domain)
    )
    return round(total / 60.0, 1)


@tool("resolve_domain", "Infer which product domain an ECR belongs to.")
def resolve_domain(
    db: Session,
    component_ids: list[str],
    requirement_ids: list[str],
    linked_requirement_ids: list[str] | None = None,
) -> str | None:
    from collections import Counter

    from app.models import Component, Requirement

    # The requirements the ECR is explicitly linked to decide its product line;
    # searched requirements and impacted components only vote when there are none.
    if linked_requirement_ids:
        linked = Counter(
            row.domain
            for row in db.query(Requirement).filter(
                Requirement.requirement_id.in_(list(linked_requirement_ids))
            )
        )
        if linked:
            return linked.most_common(1)[0][0]

    votes: Counter[str] = Counter()
    if component_ids:
        for row in db.query(Component).filter(Component.component_id.in_(component_ids)).all():
            votes[row.domain] += 2
    if requirement_ids:
        for row in db.query(Requirement).filter(
            Requirement.requirement_id.in_(requirement_ids)
        ).all():
            votes[row.domain] += 1
    return votes.most_common(1)[0][0] if votes else None
