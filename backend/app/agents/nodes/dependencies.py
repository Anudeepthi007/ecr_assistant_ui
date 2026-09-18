"""Retrieval Agent step: dependency analysis.

Walks the component graph in both directions from the changed components:
downstream (who depends on us = regression blast radius) and upstream (what we
rely on), with a decayed propagation score per hop and the critical paths that
reach the change from an entry point.
"""
from __future__ import annotations

from typing import Any

from app.agents.tools.dependency_tools import (
    build_graph,
    critical_paths,
    dependency_subgraph,
    downstream_walk,
    upstream_walk,
)
from app.agents.tools.test_tools import resolve_domain
from app.database import session_scope
from app.llm.provider import get_llm
from app.models import Component
from app.schemas.impact import DependencyAnalysis, DependencyEdge, DependencyNode


def dependency_step(state: dict[str, Any]) -> dict[str, Any]:
    analysis = state.get("ecr_analysis") or {}
    code_impact = state.get("code_impact") or {}
    requirement_analysis = state.get("requirement_analysis") or {}

    ecr = state.get("ecr_input") or {}

    with session_scope() as db:
        graph = build_graph(db)
        # Stay inside the ECR's product line, decided by its linked requirements:
        # searched requirements can belong to another domain (a rail change must
        # not walk the payments graph).
        domain = resolve_domain(db, [], [], list(ecr.get("linked_requirements") or []))
        in_domain = (
            {c.component_id for c in db.query(Component).filter(Component.domain == domain)}
            if domain
            else None
        )

    def keep(ids: list[str]) -> list[str]:
        return sorted({c for c in ids if in_domain is None or c in in_domain})

    # Seed from the strongest evidence: resolved code beats keyword candidates,
    # which beat requirement links. Mixing them would walk the graph from
    # components the change never actually touches.
    code_components = list(code_impact.get("impacted_services") or [])
    seeds = (
        keep(code_components)
        or keep(analysis.get("candidate_components") or [])
        or keep(requirement_analysis.get("impacted_components") or [])
    )

    downstream = downstream_walk(graph, seeds, depth=3)
    upstream = upstream_walk(graph, seeds, depth=2)
    propagation = graph.propagation_scores(seeds, max_depth=3)
    paths = critical_paths(graph, seeds, max_paths=5)
    subgraph = dependency_subgraph(graph, seeds, depth=2)

    direct = sorted([c for c, distance in downstream.items() if distance == 1])
    indirect = sorted([c for c, distance in downstream.items() if distance > 1])

    nodes = [
        DependencyNode(
            component_id=component_id,
            name=graph.node(component_id).get("name", component_id),
            type=graph.node(component_id).get("type", "SERVICE"),
            business_criticality=graph.node(component_id).get("business_criticality", "MEDIUM"),
            distance=0 if component_id in seeds else downstream.get(component_id, upstream.get(component_id, 0)),
            relation=(
                "SEED"
                if component_id in seeds
                else "DOWNSTREAM"
                if component_id in downstream
                else "UPSTREAM"
            ),
        )
        for component_id in {*seeds, *downstream, *upstream}
    ]
    edges = [
        DependencyEdge(
            source=edge["source"],
            target=edge["target"],
            dependency_type=edge.get("dependency_type", "SYNC_API"),
            criticality=edge.get("criticality", "MEDIUM"),
        )
        for edge in subgraph["edges"]
    ]

    confidence = round(
        min(0.96, 0.45 + 0.3 * bool(seeds) + 0.15 * min(1.0, len(downstream) / 4.0) + 0.06),
        3,
    )
    named = lambda ids: ", ".join(graph.node(c).get("name", c) for c in ids) or "none"
    baseline = (
        f"Seeded the walk from {named(seeds)}. "
        f"{len(direct)} component(s) depend on the change directly ({named(direct)}) and "
        f"{len(indirect)} indirectly ({named(indirect)}). "
        f"The change reaches {len(downstream)} component(s) in total."
    )
    reasoning = get_llm().narrate(
        task="Explain how this change propagates through the service dependency graph",
        context={
            "seeds": seeds,
            "direct_dependents": direct,
            "indirect_dependents": indirect,
            "critical_paths": paths[:3],
        },
        fallback=baseline,
    )

    result = DependencyAnalysis(
        seed_components=seeds,
        direct_dependencies=direct,
        indirect_dependencies=indirect,
        upstream_components=sorted(upstream),
        downstream_components=sorted(downstream),
        critical_dependency_paths=paths,
        blast_radius=len(downstream),
        nodes=nodes,
        edges=edges,
        confidence=confidence,
        reasoning=reasoning,
    )
    return {
        "dependency_analysis": {
            **result.model_dump(mode="json"),
            "propagation": propagation,
            "distances": downstream,
            "graph_stats": graph.stats(),
        },
        "tools_used": {
            "dependencies": [
                "build_graph",
                "downstream_walk",
                "upstream_walk",
                "critical_paths",
            ]
        },
        "_confidence": confidence,
        "_reasoning": reasoning,
        "_summary": {
            "seeds": seeds,
            "blast_radius": len(downstream),
            "direct": direct,
            "indirect": indirect,
        },
    }
