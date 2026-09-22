"""ECRs imported from the change-tracking export (ECR-1, ECR-2) keep every exported value."""
from __future__ import annotations

from app.agents.orchestrator import run_workflow
from app.database import session_scope
from app.repositories import ECRRepository
from app.services.chat_service import detect_intent

ECR_1_TESTS = {"L2R26:TC1", "L2R26:TC2", "L2R26:TC3", "L2R35:TC1", "L2R35:TC2"}


def test_ecr_2_returns_the_exported_values(client):
    ecr = client.get("/api/ecr/ECR-2").json()
    assert ecr["record_type"] == "ECR"
    assert ecr["title"] == (
        "Port Build 7 ECR -2 to Build 8: Flrt3: Horn state doesn't change on brake/horn interface screen"
    )
    assert ecr["lifecycle_status"] == "System Verified"
    assert ecr["severity"] == "Minor"
    assert ecr["assigned_testers"] == ["Anirudh"]
    assert ecr["actual_modified_objects"] == ["Brake Interface"]
    assert ecr["planned_modified_objects"] == ["Brake Interface"]
    assert ecr["build_resolved_in"] == "6.5.7.0.ENG1"
    assert (ecr["estimate"], ecr["test_estimate"], ecr["test_actual_time"]) == ("8 hours", "4", "4 hours")
    assert (ecr["creation_date"], ecr["modified_date"]) == ("Apr 22, 2026, 6:44 PM", "Jun 10, 2026, 6:54 AM")
    assert ecr["affected_test_cases"] == [
        "L2R01:TC1", "L2R01:TC2", "L2R01:TC3", "L2R05:TC1", "L2R05:TC2", "L2R05:TC3", "L2R05:TC4",
    ]
    assert ecr["description"].startswith('When the Horn key is pressed on the "brake/horn interface" screen')
    assert ecr["steps_to_reproduce"].splitlines()[0] == "1. Set control type SR-FLRT3-DMU and bring OB to cutout"
    assert len(ecr["steps_to_reproduce"].splitlines()) == 6
    assert ecr["observed_behavior"] == (
        "On pressing the Horn key, OB keeps showing the Horn state field status as Inactive"
    )
    assert ecr["expected_behavior"] == "OB should update the horn state field as Active"
    assert ecr["attachments"] == ["Logs.zip", "dev_logs.log", "test artifacts.zip"]


def test_ecr_1_returns_the_exported_values(client):
    ecr = client.get("/api/ecr/ecr-1").json()  # ids are case-insensitive
    assert ecr["title"] == "Port Build 7 ECR -1 to Build 8: Depart test not perfomed well"
    assert (ecr["lifecycle_status"], ecr["severity"]) == ("System Verified", "Medium")
    assert ecr["assigned_testers"] == ["Deepak Yadav"]
    assert ecr["actual_modified_objects"] == ["Depart Test"]
    assert (ecr["estimate"], ecr["test_estimate"], ecr["test_actual_time"]) == ("16 hours", "4", "4 hours")
    assert (ecr["creation_date"], ecr["modified_date"]) == ("May 6, 2026, 2:42 PM", "Jun 9, 2026, 3:27 PM")
    assert set(ecr["affected_test_cases"]) == ECR_1_TESTS
    assert '-send 1010 "Command locomotive system state to Non-controlling"' in ecr["description"]
    assert ecr["attachments"] == ["test.log", "Fixed_ecr.rtf"]
    assert ecr["steps_to_reproduce"] == ""


def test_analysis_recommends_every_listed_test_first(rag):
    with session_scope() as db:
        ecr = ECRRepository(db).get("ECR-1").as_dict()
    _, state = run_workflow(ecr, {})
    selected = state["test_selection"]["selected_tests"]
    assert ECR_1_TESTS <= {t["test_case_id"] for t in selected}
    assert all(t["domain"] == "rail" for t in selected)
    ordered = [t["test_case_id"] for t in state["test_prioritization"]["prioritized_tests"]]
    assert set(ordered[: len(ECR_1_TESTS)]) == ECR_1_TESTS
    listed = [t for t in selected if t["test_case_id"] in ECR_1_TESTS]
    assert all(t["reason"].startswith("Listed as an affected test case on the ECR") for t in listed)
    assert {"L2R26", "L2R35"} <= {r["requirement_id"] for r in state["requirements"]}


def test_analysing_keeps_the_exported_status(client):
    client.post("/api/ecr/ECR-2/analyze?wait=true", json={})
    ecr = client.get("/api/ecr/ECR-2").json()
    assert ecr["lifecycle_status"] == "System Verified"   # the export's status is untouched
    assert ecr["status"] == "ANALYSED"                     # the app's own analysis state


def test_chat_understands_short_ecr_ids_and_export_test_ids():
    detection = detect_intent("why was L2R26: TC2 selected for ECR-1?")
    assert detection["ecr_id"] == "ECR-1"
    assert "L2R26:TC2" in detection["artifacts"]
    assert detect_intent("analyse ECR-2026-001")["ecr_id"] == "ECR-2026-001"
    assert detect_intent("what about ecr 2026 7")["ecr_id"] == "ECR-2026-7"


def test_every_ecr_shows_only_its_own_data(rag):
    """ECR-1 gets its own requirements, tests, components, defects and evidence - nothing wider."""
    with session_scope() as db:
        ecr = ECRRepository(db).get("ECR-1").as_dict()
    _, state = run_workflow(ecr, {})
    assert {r["requirement_id"] for r in state["requirements"]} == {"L2R26", "L2R35"}
    assert {t["test_case_id"] for t in state["test_selection"]["selected_tests"]} == ECR_1_TESTS
    assert {e["title"] for e in state["evidence"]} == {"test.log", "Fixed_ecr.rtf"}
    assert all(e["ecr_id"] == "ECR-1" for e in state["evidence"])
    assert state["comments"] == []
    assert state["defects"] == []  # no defect in the data is linked to L2R26 or L2R35
    impact = state["impact_analysis"]
    assert [c["component_id"] for c in impact["directly_impacted_components"]] == ["RCMP-002"]
    assert {c["component_id"] for c in impact["indirectly_impacted_components"]} == {
        "RCMP-001", "RCMP-003", "RCMP-005", "RCMP-009",  # the other components L2R26/L2R35 name
    }
    assert state["defect_insights"]["component_history"] == []


def test_sample_ecrs_are_scoped_to_their_linked_requirements(rag):
    with session_scope() as db:
        ecr = ECRRepository(db).get("ECR-2026-002").as_dict()
    _, state = run_workflow(ecr, {})
    assert {r["requirement_id"] for r in state["requirements"]} == set(ecr["linked_requirements"])
    selected = {t["test_case_id"] for t in state["test_selection"]["selected_tests"]}
    assert selected == set(ecr["affected_test_cases"])
    assert all(t["requirement_id"] in ecr["linked_requirements"] for t in state["test_selection"]["selected_tests"])
    assert all(c["ecr_id"] == "ECR-2026-002" for c in state["comments"])
