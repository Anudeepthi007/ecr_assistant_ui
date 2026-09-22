"""Test discovery, selection and prioritisation steps.

Discovery casts a wide net through three channels; selection then scores every
candidate with the explainable algorithm and drops what does not earn its place;
prioritisation orders what remains for the fastest feedback.
"""
from __future__ import annotations

from typing import Any

from app.agents.tools.test_tools import (
    baseline_duration,
    resolve_domain,
    semantic_test_search,
    tests_by_component,
    tests_by_requirement,
    total_test_inventory,
)
from app.agents.nodes.scope import is_scoped, linked_requirement_ids, listed_test_ids
from app.database import session_scope
from app.llm.provider import get_llm
from app.models import Component, TestCase
from app.schemas.test_case import (
    SelectedTest,
    TestCaseRead,
    TestDiscovery,
    TestPrioritization,
    TestSelection,
)
from app.services.test_selection_service import (
    SelectionContext,
    get_selection_engine,
    priority_distribution,
)


def test_discovery_step(state: dict[str, Any]) -> dict[str, Any]:
    ecr = state["ecr_input"]
    analysis = state.get("ecr_analysis") or {}
    impact = state.get("impact_analysis") or {}
    requirements = state.get("requirements") or []

    requirement_ids = [r["requirement_id"] for r in requirements]
    component_ids = sorted(
        {
            *(c["component_id"] for c in impact.get("directly_impacted_components") or []),
            *(c["component_id"] for c in impact.get("indirectly_impacted_components") or []),
        }
    )
    query = f"{ecr.get('title', '')}. {ecr.get('description', '')}"
    keywords = analysis.get("technical_keywords") or []

    listed = listed_test_ids(ecr)
    scoped = is_scoped(ecr)  # the ECR's own requirements and listed tests only
    with session_scope() as db:
        by_listing = (
            [row.as_dict() for row in db.query(TestCase).filter(TestCase.test_case_id.in_(listed))]
            if listed
            else []
        )
        by_requirement = tests_by_requirement(
            db, sorted(linked_requirement_ids(ecr)) if scoped else requirement_ids
        )
        by_component = [] if scoped else tests_by_component(db, component_ids)
        domain = resolve_domain(
            db, component_ids, requirement_ids, list(ecr.get("linked_requirements") or [])
        )
        total_available = total_test_inventory(db, domain)
        baseline_minutes = baseline_duration(db, domain)
    semantic_hits = semantic_test_search(query, keywords=keywords, k=80)
    by_semantic = [] if scoped else semantic_hits  # in scope, similarity only scores

    candidates: dict[str, dict[str, Any]] = {}
    raw_semantic = {
        payload["test_case_id"]: float(payload.get("semantic_score", 0.0)) for payload in semantic_hits
    }
    # Hybrid retrieval scores saturate well below 100 on short enterprise
    # artifacts, so normalise against the best hit in this candidate set. The
    # factor then measures "how close to the best semantic match is this test",
    # which is what the P0..P3 bands are calibrated against.
    best_semantic = max(raw_semantic.values(), default=0.0)
    semantic_scores = {
        test_id: round(100.0 * score / best_semantic, 1) if best_semantic else 0.0
        for test_id, score in raw_semantic.items()
    }
    for payload in by_listing:  # named on the ECR: always a candidate
        candidates.setdefault(payload["test_case_id"], dict(payload))
    for payload in [*by_requirement, *by_component, *by_semantic]:
        test_id = payload.get("test_case_id")
        if not test_id or payload.get("retired"):
            continue
        if domain and payload.get("domain") and payload["domain"] != domain:
            continue  # never pull another product line into this suite
        candidates.setdefault(test_id, dict(payload))

    channels = {
        "listed_on_ecr": len(by_listing),
        "requirement_trace": len(by_requirement),
        "component_coverage": len(by_component),
        "semantic_search": len(by_semantic),
        "unique_candidates": len(candidates),
    }
    confidence = round(min(0.95, 0.5 + 0.3 * bool(by_requirement) + 0.15 * bool(candidates)), 3)
    reasoning = (
        f"Found {len(candidates)} test case(s) from this ECR's own data: the test cases it lists "
        f"and the tests of its linked requirements."
        if scoped
        else f"Discovered {len(candidates)} unique candidate test(s) out of {total_available} "
        f"{domain or 'catalogue'} test(s): {channels['requirement_trace']} via requirement traceability, "
        f"{channels['component_coverage']} via component coverage and "
        f"{channels['semantic_search']} via semantic search."
    )

    discovery = TestDiscovery(
        candidate_tests=[
            TestCaseRead(**{k: v for k, v in payload.items() if k in TestCaseRead.model_fields})
            for payload in candidates.values()
        ],
        total_available=total_available,
        discovery_channels=channels,
        confidence=confidence,
        reasoning=reasoning,
    )
    return {
        "discovered_tests": list(candidates.values()),
        "test_discovery": {
            **discovery.model_dump(mode="json"),
            "semantic_scores": semantic_scores,
            "baseline_duration_minutes": baseline_minutes,
            "domain": domain,
        },
        "tools_used": {
            "test_discovery": [
                "tests_by_requirement",
                "tests_by_component",
                "semantic_test_search",
                "total_test_inventory",
            ]
        },
        "_confidence": confidence,
        "_reasoning": reasoning,
        "_summary": {
            "candidates": len(candidates),
            "total_available": total_available,
            "domain": domain or "all",
            **channels,
        },
    }


def _selection_context(state: dict[str, Any]) -> SelectionContext:
    impact = state.get("impact_analysis") or {}
    dependency = state.get("dependency_analysis") or {}
    defect = state.get("defect_analysis") or {}
    discovery = state.get("test_discovery") or {}
    analysis = state.get("ecr_analysis") or {}

    with session_scope() as db:
        criticality = {c.component_id: c.business_criticality for c in db.query(Component).all()}

    return SelectionContext(
        matched_requirements={
            r["requirement_id"]: float(r.get("relevance", 0.0))
            for r in state.get("requirements") or []
        },
        direct_components={
            c["component_id"] for c in impact.get("directly_impacted_components") or []
        },
        indirect_components={
            c["component_id"] for c in impact.get("indirectly_impacted_components") or []
        },
        dependency_distance={k: int(v) for k, v in (dependency.get("distances") or {}).items()},
        propagation={k: float(v) for k, v in (dependency.get("propagation") or {}).items()},
        component_criticality=criticality,
        defect_components=set(defect.get("defect_prone_components") or []),
        semantic_scores={k: float(v) for k, v in (discovery.get("semantic_scores") or {}).items()},
        affected_features=set(analysis.get("affected_features") or []),
        listed_tests=set(listed_test_ids(state.get("ecr_input") or {})),
    )


def test_selection_step(state: dict[str, Any]) -> dict[str, Any]:
    discovered = state.get("discovered_tests") or []
    discovery = state.get("test_discovery") or {}
    context = _selection_context(state)
    engine = get_selection_engine()
    selected, rejected = engine.select(discovered, context)

    total_available = int(discovery.get("total_available", 0) or 0)
    baseline_minutes = float(discovery.get("baseline_duration_minutes", 0.0) or 0.0)
    estimated = round(sum(t.average_execution_time for t in selected) / 60.0, 1)
    reduction = round(100 * (1 - len(selected) / total_available), 1) if total_available else 0.0

    confidence = round(min(0.95, 0.55 + 0.25 * bool(selected) + 0.15 * bool(context.matched_requirements)), 3)
    reasoning = (
        f"Scored {len(discovered)} candidate(s) from this ECR's own test cases and selected "
        f"{len(selected)} test(s)."
    )

    selection = TestSelection(
        selected_tests=selected,
        excluded_count=len(rejected),
        total_available=total_available,
        total_candidates=len(discovered),
        reduction_percentage=reduction,
        estimated_duration_minutes=estimated,
        baseline_duration_minutes=baseline_minutes,
        priority_distribution=priority_distribution(selected),
        confidence=confidence,
        reasoning=reasoning,
    )
    return {
        "selected_tests": [t.model_dump(mode="json") for t in selected],
        "test_selection": selection.model_dump(mode="json"),
        "tools_used": {"test_selection": ["selection_engine.select"]},
        "_confidence": confidence,
        "_reasoning": reasoning,
        "_summary": {
            "selected": len(selected),
            "total_available": total_available,
            "reduction_percentage": reduction,
            "priority_distribution": priority_distribution(selected),
        },
    }


def test_prioritization_step(state: dict[str, Any]) -> dict[str, Any]:
    selected = [SelectedTest.model_validate(t) for t in state.get("selected_tests") or []]
    context = _selection_context(state)
    ordered = get_selection_engine().prioritise(selected, context)

    waves: dict[str, list[str]] = {"P0": [], "P1": [], "P2": [], "P3": []}
    for test in ordered:
        waves[test.priority.value].append(test.test_case_id)
    total_minutes = round(sum(t.average_execution_time for t in ordered) / 60.0, 1)
    critical_minutes = round(
        sum(t.average_execution_time for t in ordered if t.priority.value in ("P0", "P1")) / 60.0, 1
    )

    strategy = (
        "Priority first: highest priority band, then the most business critical component, then "
        "relevance, then shortest first so failures surface early."
    )
    confidence = round(min(0.95, 0.6 + 0.3 * bool(ordered)), 3)
    baseline = (
        f"Ordered {len(ordered)} test(s): {len(waves['P0'])} P0, {len(waves['P1'])} P1, "
        f"{len(waves['P2'])} P2, {len(waves['P3'])} P3. Run the P0 and P1 bands first, "
        f"then the rest of the selection."
    )
    # Execution-time estimates are deliberately kept out of the narrative and out of
    # the model's context, so no report claims how long a suite takes to run.
    reasoning = get_llm().narrate(
        task="Explain the recommended regression execution order",
        context={
            "waves": {k: v[:6] for k, v in waves.items()},
            "strategy": strategy,
        },
        fallback=baseline,
    )

    prioritization = TestPrioritization(
        prioritized_tests=ordered,
        waves=waves,
        estimated_duration_minutes=total_minutes,
        critical_path_minutes=critical_minutes,
        strategy=strategy,
        confidence=confidence,
        reasoning=reasoning,
    )
    return {
        "prioritized_tests": [t.model_dump(mode="json") for t in ordered],
        "test_prioritization": prioritization.model_dump(mode="json"),
        "tools_used": {"test_prioritization": ["selection_engine.prioritise"]},
        "_confidence": confidence,
        "_reasoning": reasoning,
        "_summary": {
            "waves": {k: len(v) for k, v in waves.items()},
            "critical_path_minutes": critical_minutes,
            "estimated_duration_minutes": total_minutes,
        },
    }
