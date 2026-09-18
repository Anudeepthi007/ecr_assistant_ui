"""Agent nodes and the orchestrated workflow (offline / mock provider)."""
from __future__ import annotations

import pytest

from app.agents.nodes.ecr_understanding import classify_change, extract_entities
from app.agents.nodes.planning import build_plan
from app.agents.orchestrator import needs_approval, run_workflow
from app.database import session_scope
from app.repositories import ECRRepository
from app.schemas.common import ChangeType


@pytest.fixture(scope="module")
def demo_state(rag):
    with session_scope() as db:
        ecr = ECRRepository(db).get("ECR-2026-001").as_dict()
    _, state = run_workflow(ecr, {"human_in_the_loop": False})
    return state


def test_classifier_separates_ui_from_database_changes():
    ui = classify_change(
        "Modify the label of the save button on the user profile page", ["portal/profile_page.py"]
    )
    database = classify_change(
        "Add a column to the transaction table and backfill historical rows",
        ["schema/transaction_schema.py"],
    )
    assert max(ui, key=ui.get) == ChangeType.UI.value
    assert max(database, key=database.get) == ChangeType.DATABASE.value


def test_entity_extraction_finds_features_and_components(database):
    entities = extract_entities(
        "Modify payment validation logic to support multi currency transactions",
        ["payment/validator.py"],
    )
    assert entities["business_domain"] == "Payments"
    assert entities["affected_features"]
    assert "CMP-004" in entities["candidate_components"]
    assert "financial_transaction" in entities["risk_indicators"]


def test_planner_skips_expensive_agents_for_a_ui_tweak():
    plan = build_plan(
        {"change_type": ChangeType.UI.value, "risk_indicators": [], "change_complexity": 0.1}, {}
    )
    assert "dependencies" in plan["skipped"]
    assert "requirements" in plan["investigations"]
    assert "historical_defects" in plan["investigations"]  # defects are always analysed
    assert plan["rationale"]


def test_planner_runs_everything_for_a_schema_change():
    plan = build_plan(
        {
            "change_type": ChangeType.DATABASE.value,
            "risk_indicators": ["schema_migration"],
            "change_complexity": 0.8,
        },
        {},
    )
    assert "dependencies" in plan["investigations"]
    assert "historical_defects" in plan["investigations"]
    assert not plan["skipped"]


def test_force_full_analysis_overrides_skipping():
    plan = build_plan(
        {"change_type": ChangeType.UI.value, "risk_indicators": [], "change_complexity": 0.1},
        {"force_full_analysis": True},
    )
    assert not plan["skipped"]


def test_workflow_produces_every_stage(demo_state):
    for key in (
        "ecr_analysis",
        "requirements",
        "defects",
        "comments",
        "evidence",
        "code_impact",
        "dependency_analysis",
        "impact_analysis",
        "test_selection",
        "test_prioritization",
        "correlation",
        "final_answer",
        "final_report",
    ):
        assert demo_state.get(key), f"missing {key}"


def test_workflow_identifies_the_expected_payment_impact(demo_state):
    impact = demo_state["impact_analysis"]
    direct = {c["component_id"] for c in impact["directly_impacted_components"]}
    indirect = {c["component_id"] for c in impact["indirectly_impacted_components"]}
    assert "CMP-004" in direct  # payment validator
    assert "CMP-005" in direct  # currency service
    assert "CMP-007" in indirect  # refund service is downstream
    assert "risk_score" not in impact


def test_workflow_selects_a_smaller_suite_than_the_baseline(demo_state):
    selection = demo_state["test_selection"]
    assert 0 < len(selection["selected_tests"]) < selection["total_available"]
    assert selection["reduction_percentage"] > 0
    assert selection["estimated_duration_minutes"] < selection["baseline_duration_minutes"]


def test_every_selected_test_is_explained(demo_state):
    for test in demo_state["test_selection"]["selected_tests"]:
        assert test["reason"]
        assert test["priority"] in ("P0", "P1", "P2", "P3")


def test_correlation_links_artefacts_to_the_ecr(demo_state):
    graph = demo_state["correlation"]["graph"]
    types = {node["type"] for node in graph["nodes"]}
    assert {"REQUIREMENT", "TEST_CASE", "DEFECT", "COMMENT", "EVIDENCE"} <= types
    assert all(edge["reason"] is not None for edge in graph["edges"])


def test_defect_analysis_explains_every_related_defect(demo_state):
    insights = demo_state["defect_insights"]
    assert insights["total"] == len(demo_state["defects"]) > 0
    selected = {t["test_case_id"] for t in demo_state["test_selection"]["selected_tests"]}
    for row in insights["defects"]:
        assert row["chance_of_recurrence"] in ("High", "Medium", "Low")
        assert row["why_it_matters"] and row["what_to_check"]
        assert set(row["covering_tests"]) <= selected
        assert row["covered"] == bool(row["covering_tests"])
    assert insights["high"] >= 1  # the payment change touches components with critical history
    # Scoped to the ECR's own data: no component-wide defect history is added.
    assert insights["scoped"] is True
    assert insights["component_history"] == []
    assert demo_state["defect_summary"]
    section = next(s for s in demo_state["final_report"]["sections"] if s["key"] == "historical_defects")
    assert section["body"] == demo_state["defect_summary"]


def test_a_saved_report_rebuilds_the_page_after_a_restart(demo_state):
    from app.api.routes.analysis import page_fields_from_report

    fields = page_fields_from_report(demo_state["final_report"])
    assert (
        fields["impact_analysis"]["directly_impacted_components"]
        == demo_state["impact_analysis"]["directly_impacted_components"]
    )
    assert "component_history" in fields["defect_insights"]
    assert fields["defect_summary"] == demo_state["defect_summary"]


def test_defect_summary_uses_component_history_when_nothing_matches():
    from app.agents.nodes.summarization import _baseline_defect_summary

    text = _baseline_defect_summary(
        "ECR-X",
        {
            "defects": [],
            "component_history": [
                {"component": "CMP-1", "component_name": "Search Service", "total": 2, "last_seen_days": 40,
                 "top_cause": "Stale cache", "impact": "Direct", "severe": 1, "open": 0, "reached_production": 1}
            ],
            "open_defects": [{"defect_id": "BUG-9", "title": "Index lag", "severity": "HIGH"}],
        },
    )
    assert "No past defect matches ECR-X directly" in text
    assert "Search Service" in text and "40 days ago" in text and "BUG-9" in text


def test_answer_cites_real_artefacts(demo_state):
    citations = demo_state["answer_citations"]
    assert citations
    known = {r["requirement_id"] for r in demo_state["requirements"]} | {
        d["defect_id"] for d in demo_state["defects"]
    } | {t["test_case_id"] for t in demo_state["test_selection"]["selected_tests"]} | {
        c["comment_id"] for c in demo_state["comments"]
    } | {e["evidence_id"] for e in demo_state["evidence"]}
    assert set(citations) <= known


def test_report_sees_every_agents_evidence(demo_state):
    """Regression: an agent's partial state must not shadow earlier agents.

    The report is assembled inside the last agent, so if the per-step view
    replaced (rather than merged) the incoming trace and confidence, the report
    would only ever contain the summarization agent's own contribution.
    """
    report = demo_state["final_report"]
    # The report cannot contain the two entries written after it is assembled:
    # its own step, and the summarization agent's node-level entry.
    assert len(report["execution_trace"]) == len(demo_state["execution_trace"]) - 2
    per_step = report["confidence"]["per_step"]
    assert {"understand_ecr", "gather_evidence", "assess_impact", "select_tests"} <= set(per_step)
    assert len(per_step) >= 5


def test_execution_trace_records_every_step(demo_state):
    trace = demo_state["execution_trace"]
    assert len(trace) == 8  # five steps + three agents
    assert all(entry["agent"] and entry["action"] for entry in trace)
    assert all(entry["status"] in ("completed", "failed") for entry in trace)


def test_ui_only_change_skips_dependency_analysis(rag):
    with session_scope() as db:
        ecr = ECRRepository(db).get("ECR-2026-002").as_dict()
    _, state = run_workflow(ecr, {})
    assert "dependencies" in state.get("skipped_steps", [])
    assert "historical_defects" not in state.get("skipped_steps", [])
    assert "defect_insights" in state and state["defect_summary"]
    assert state["impact_analysis"]["directly_impacted_components"]


def test_rail_domain_change_stays_in_its_own_suite(rag):
    with session_scope() as db:
        ecr = ECRRepository(db).get("ECR-2026-012").as_dict()
    _, state = run_workflow(ecr, {})
    selected = state["test_selection"]["selected_tests"]
    assert selected
    assert all(test["domain"] == "rail" for test in selected)


def test_approval_gate_is_only_entered_when_requested():
    on = {"options": {"human_in_the_loop": True}, "impact_analysis": {}}
    off = {"options": {}, "impact_analysis": {}}
    assert needs_approval(on) == "human_approval"
    assert needs_approval(off) == "summarization_agent"
