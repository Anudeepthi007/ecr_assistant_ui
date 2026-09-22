"""Correlation layer.

Builds one explicit traceability bundle for the ECR:

    ECR -> requirements -> test cases
        -> historical defects -> components
        -> review comments -> evidence

Every link records *why* it exists, which is what makes the final answer
citable rather than a guess.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.agents.tools.registry import tool
from app.database import session_scope
from app.models import Component


@tool("build_correlation_graph", "Link every retrieved artifact to the ECR with a typed edge.")
def build_correlation_graph(state: dict[str, Any]) -> dict[str, Any]:
    ecr_id = state.get("ecr_id", "")
    requirements = state.get("requirements") or []
    defects = state.get("defects") or []
    comments = state.get("comments") or []
    evidence = state.get("evidence") or []
    selected = state.get("selected_tests") or []
    impact = state.get("impact_analysis") or {}

    nodes: list[dict[str, Any]] = [
        {"id": ecr_id, "type": "ECR", "label": state.get("ecr_input", {}).get("title", ecr_id)}
    ]
    edges: list[dict[str, Any]] = []

    def add_node(node_id: str, node_type: str, label: str, **extra: Any) -> None:
        if not node_id or any(n["id"] == node_id for n in nodes):
            return
        nodes.append({"id": node_id, "type": node_type, "label": label, **extra})

    def add_edge(source: str, target: str, relation: str, reason: str, weight: float = 1.0) -> None:
        if not source or not target:
            return
        edges.append(
            {"source": source, "target": target, "relation": relation, "reason": reason, "weight": weight}
        )

    for requirement in requirements:
        rid = requirement["requirement_id"]
        add_node(rid, "REQUIREMENT", requirement.get("title", rid), priority=requirement.get("priority"))
        add_edge(
            ecr_id,
            rid,
            "IMPACTS_REQUIREMENT",
            requirement.get("reason", ""),
            round(float(requirement.get("relevance", 0)) / 100.0, 3),
        )
        for component_id in [requirement.get("component"), *(requirement.get("linked_components") or [])]:
            if component_id:
                add_edge(rid, component_id, "IMPLEMENTED_BY", "Requirement is realised by this component", 0.8)

    for defect in defects:
        did = defect["defect_id"]
        add_node(did, "DEFECT", defect.get("title", did), severity=defect.get("severity"))
        add_edge(
            ecr_id,
            did,
            "SIMILAR_HISTORY",
            defect.get("reason", ""),
            round(float(defect.get("similarity", 0)) / 100.0, 3),
        )
        add_edge(did, defect.get("affected_component", ""), "AFFECTED", "Defect was raised on this component", 0.7)

    for test in selected:
        tid = test["test_case_id"]
        add_node(tid, "TEST_CASE", test.get("title", tid), priority=test.get("priority"))
        add_edge(
            ecr_id,
            tid,
            "RECOMMENDED_TEST",
            test.get("reason", ""),
            round(float(test.get("relevance_score", 0)) / 100.0, 3),
        )
        if test.get("requirement_id"):
            add_edge(test["requirement_id"], tid, "VERIFIED_BY", "Test verifies this requirement", 0.9)

    for comment in comments:
        cid = comment["comment_id"]
        add_node(cid, "COMMENT", f"{comment.get('author', '')}: {comment.get('category', '')}")
        add_edge(
            comment.get("target_id") or ecr_id,
            cid,
            "DISCUSSED_IN",
            f"{comment.get('category', 'Discussion')} raised by {comment.get('author', 'a reviewer')}",
            0.6,
        )
        for reference in comment.get("references") or []:
            add_edge(cid, reference, "REFERENCES", "Comment explicitly references this artifact", 0.5)

    for item in evidence:
        eid = item["evidence_id"]
        add_node(eid, "EVIDENCE", item.get("title", eid), outcome=item.get("outcome"))
        add_edge(
            item.get("target_id") or ecr_id,
            eid,
            "EVIDENCED_BY",
            f"{item.get('evidence_type', 'Artifact')} with outcome {item.get('outcome', 'UNKNOWN')}",
            0.7,
        )

    for component in [
        *(impact.get("directly_impacted_components") or []),
        *(impact.get("indirectly_impacted_components") or []),
    ]:
        add_node(
            component["component_id"],
            "COMPONENT",
            component.get("name", component["component_id"]),
            criticality=component.get("business_criticality"),
        )
        add_edge(
            ecr_id,
            component["component_id"],
            "IMPACTS_COMPONENT" if component.get("impact_type") == "DIRECT" else "TOUCHES_COMPONENT",
            "; ".join(component.get("reasons") or []),
            round(float(component.get("impact_score", 0)) / 100.0, 3),
        )

    known = {node["id"] for node in nodes}
    edges = [edge for edge in edges if edge["source"] in known and edge["target"] in known]
    return {"nodes": nodes, "edges": edges}


def correlation_step(state: dict[str, Any]) -> dict[str, Any]:
    graph = build_correlation_graph(state)
    ecr_id = state.get("ecr_id", "")

    by_type: dict[str, int] = defaultdict(int)
    for node in graph["nodes"]:
        by_type[node["type"]] += 1
    relations: dict[str, int] = defaultdict(int)
    for edge in graph["edges"]:
        relations[edge["relation"]] += 1

    # Cross-source corroboration: artifacts named by more than one source are the
    # ones a human would otherwise have to join up manually.
    mention_count: dict[str, set[str]] = defaultdict(set)
    for comment in state.get("comments") or []:
        for reference in comment.get("references") or []:
            mention_count[reference].add("comment")
    for item in state.get("evidence") or []:
        if item.get("target_id"):
            mention_count[item["target_id"]].add("evidence")
    for requirement in state.get("requirements") or []:
        mention_count[requirement["requirement_id"]].add("requirement_search")
    for defect in state.get("defects") or []:
        mention_count[defect["defect_id"]].add("defect_search")
    for test in state.get("selected_tests") or []:
        mention_count[test["test_case_id"]].add("test_selection")

    corroborated = sorted(
        (
            {"artifact": artifact, "sources": sorted(sources), "source_count": len(sources)}
            for artifact, sources in mention_count.items()
            if len(sources) > 1
        ),
        key=lambda item: item["source_count"],
        reverse=True,
    )

    with session_scope() as db:
        component_names = {c.component_id: c.name for c in db.query(Component).all()}

    coverage = {
        "requirements": len(state.get("requirements") or []),
        "tests_selected": len(state.get("selected_tests") or []),
        "defects": len(state.get("defects") or []),
        "comments": len(state.get("comments") or []),
        "evidence": len(state.get("evidence") or []),
        "components": by_type.get("COMPONENT", 0),
    }
    confidence = round(
        min(0.96, 0.5 + 0.08 * sum(1 for value in coverage.values() if value)), 3
    )
    reasoning = (
        f"Correlated {len(graph['nodes'])} artifact(s) and {len(graph['edges'])} typed link(s) "
        f"for {ecr_id} across {sum(1 for v in coverage.values() if v)} source(s). "
        f"{len(corroborated)} artifact(s) are corroborated by more than one source."
    )

    return {
        "correlation": {
            "graph": graph,
            "node_types": dict(by_type),
            "relations": dict(relations),
            "coverage": coverage,
            "corroborated": corroborated[:12],
            "component_names": component_names,
            "confidence": confidence,
            "reasoning": reasoning,
        },
        "tools_used": {"correlation": ["build_correlation_graph"]},
        "_confidence": confidence,
        "_reasoning": reasoning,
        "_summary": {
            "nodes": len(graph["nodes"]),
            "edges": len(graph["edges"]),
            "coverage": coverage,
            "corroborated": len(corroborated),
        },
    }
