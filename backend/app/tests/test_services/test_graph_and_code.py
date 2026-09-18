"""Dependency graph traversal, code analysis and retrieval."""
from __future__ import annotations

from app.graph.dependency_graph import DependencyGraphService, build_dependency_graph
from app.services.code_analysis_service import CodeAnalysisService
from app.vectorstore import COLLECTION_DEFECTS, COLLECTION_REQUIREMENTS


def test_graph_loads_both_domains(db_session):
    graph = build_dependency_graph(db_session)
    stats = graph.stats()
    assert stats["nodes"] == 55  # 35 commerce + 20 rail
    assert stats["edges"] == 72


def test_downstream_finds_the_blast_radius(db_session):
    graph = build_dependency_graph(db_session)
    downstream = graph.downstream(["CMP-004"], max_depth=3)  # payment validator
    # payment and refund depend on the shared validator; order/gateway follow
    assert "CMP-003" in downstream and downstream["CMP-003"] == 1
    assert "CMP-007" in downstream and downstream["CMP-007"] == 1
    assert "CMP-006" in downstream
    assert "CMP-002" in downstream


def test_upstream_finds_what_the_change_relies_on(db_session):
    graph = build_dependency_graph(db_session)
    upstream = graph.upstream(["CMP-003"], max_depth=2)
    assert "CMP-004" in upstream  # payment -> validator
    assert "CMP-005" in upstream  # payment -> currency
    assert "CMP-008" in upstream  # payment -> transaction db


def test_propagation_decays_with_distance(db_session):
    graph = build_dependency_graph(db_session)
    scores = graph.propagation_scores(["CMP-004"], max_depth=3)
    assert scores["CMP-003"] > scores["CMP-002"]
    assert all(0.0 < value <= 1.0 for value in scores.values())


def test_edge_propagation_ranks_coupling_types():
    library = DependencyGraphService.edge_propagation("LIBRARY", "CRITICAL")
    event = DependencyGraphService.edge_propagation("ASYNC_EVENT", "CRITICAL")
    assert library > event


def test_critical_paths_reach_the_change(db_session):
    graph = build_dependency_graph(db_session)
    paths = graph.critical_paths(["CMP-004"], max_paths=3)
    assert paths
    assert all(path[-1] == "CMP-004" for path in paths)


def test_python_ast_analyzer_resolves_direct_and_indirect_impact():
    service = CodeAnalysisService()
    result = service.analyze_change(["payment/validator.py", "payment/currency.py"])
    assert set(result["resolved_modules"]) == {"payment.validator", "payment.currency"}
    assert "CMP-004" in result["direct_components"]
    # refund and payment services import the shared validator
    assert "refund.service" in result["dependent_modules"]
    assert "CMP-007" in result["indirect_components"]
    assert 0.0 < result["change_surface"] <= 1.0


def test_code_analyzer_uses_keywords_when_no_files_are_declared():
    service = CodeAnalysisService()
    result = service.analyze_change([], keywords=["currency"])
    assert result["resolved_modules"]  # keyword discovery kicked in


def test_unknown_declared_files_do_not_pull_in_unrelated_modules():
    """Regression: rail onboard files made keyword search report payment modules as changed."""
    service = CodeAnalysisService()
    result = service.analyze_change(["onboard/consist.py"], keywords=["validate", "currency"])
    assert result["unresolved_files"] == ["onboard/consist.py"]
    assert not result["resolved_modules"]
    assert not result["direct_components"]


def test_component_mapping_prefers_the_most_specific_path():
    service = CodeAnalysisService()
    assert service.component_for_path("payment/validator.py") == "CMP-004"
    assert service.component_for_path("payment/service.py") == "CMP-003"
    assert service.component_for_path("schema/transaction_schema.py") == "CMP-008"


def test_rag_retrieves_the_expected_requirement(rag):
    hits = rag.retrieve(
        COLLECTION_REQUIREMENTS,
        "multi currency payment validation for unsupported currency codes",
        k=5,
    )
    ids = [hit.id for hit in hits]
    assert "REQ-1003" in ids or "REQ-1004" in ids
    assert hits[0].relevance > 0


def test_rag_separates_unrelated_domains(rag):
    hits = rag.retrieve(COLLECTION_DEFECTS, "depart test key availability onboard state", k=5)
    ids = [hit.id for hit in hits]
    assert any(defect.startswith("PTC-") for defect in ids)
