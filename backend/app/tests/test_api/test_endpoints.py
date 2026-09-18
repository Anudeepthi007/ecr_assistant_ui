"""API contract tests (offline provider, seeded database)."""
from __future__ import annotations

import pytest


def test_health_reports_subsystems(client):
    payload = client.get("/api/health").json()
    assert payload["status"] == "ok"
    assert payload["database"]["ok"] is True
    assert payload["demo_mode"] is True  # tests force the mock provider
    assert payload["code_analysis"]["modules"] > 0


def test_data_health_counts_the_seeded_corpus(client):
    counts = client.get("/api/health/data").json()
    assert counts["components"] == 55
    assert counts["requirements"] == 64
    assert counts["test_cases"] == 251
    assert counts["defects"] == 68 and counts["ecrs"] == 45
    assert counts["comments"] > 0 and counts["evidence"] > 0


def test_list_and_search_ecrs(client):
    all_ecrs = client.get("/api/ecr").json()
    assert len(all_ecrs) == 45
    matched = client.get("/api/ecr?search=currency").json()
    assert any(item["ecr_id"] == "ECR-2026-001" for item in matched)


def test_get_ecr_and_missing_ecr(client):
    assert client.get("/api/ecr/ECR-2026-001").json()["ecr_id"] == "ECR-2026-001"
    assert client.get("/api/ecr/ECR-9999-999").status_code == 404


def test_ecr_id_is_case_insensitive(client):
    assert client.get("/api/ecr/ecr-2026-001").json()["ecr_id"] == "ECR-2026-001"


def test_sources_endpoint_returns_the_raw_multisource_view(client):
    payload = client.get("/api/ecr/ECR-2026-001/sources").json()
    assert payload["ecr"]["ecr_id"] == "ECR-2026-001"
    assert payload["comments"] and payload["evidence"]


def test_create_ecr_generates_an_id_and_rejects_duplicates(client):
    created = client.post(
        "/api/ecr",
        json={
            "title": "Adjust refund rounding for zero-decimal currencies",
            "description": "Refund amounts for JPY must not be multiplied by 100.",
            "changed_files": ["refund/service.py"],
        },
    )
    assert created.status_code == 201
    ecr_id = created.json()["ecr_id"]
    assert ecr_id.startswith("ECR-")

    duplicate = client.post(
        "/api/ecr", json={"ecr_id": ecr_id, "title": "Duplicate", "description": "x"}
    )
    assert duplicate.status_code == 409


def test_create_ecr_validates_input(client):
    assert client.post("/api/ecr", json={"title": "x"}).status_code == 422


@pytest.fixture(scope="module")
def analysed(client):
    response = client.post("/api/ecr/ECR-2026-001/analyze?wait=true", json={})
    assert response.status_code == 202
    return response.json()


def test_analysis_returns_every_section(client, analysed):
    payload = client.get("/api/ecr/ECR-2026-001/analysis").json()
    assert payload["status"] == "COMPLETED"
    assert payload["answer"]
    assert payload["impact_analysis"]["directly_impacted_components"]
    assert payload["test_selection"]["selected_tests"]
    assert payload["correlation"]["graph"]["nodes"]


def test_impact_endpoint(client, analysed):
    payload = client.get("/api/ecr/ECR-2026-001/impact").json()
    assert "risk_level" not in payload["impact"]
    assert payload["dependency"]["blast_radius"] >= 0


def test_tests_endpoint_filters_by_priority(client, analysed):
    everything = client.get("/api/ecr/ECR-2026-001/tests").json()
    p0 = client.get("/api/ecr/ECR-2026-001/tests?priority=P0").json()
    assert everything["selected"] > 0
    assert all(test["priority"] == "P0" for test in p0["tests"])
    assert len(p0["tests"]) <= everything["selected"]


def test_workflow_endpoint_exposes_the_trace(client, analysed):
    payload = client.get("/api/ecr/ECR-2026-001/workflow").json()
    assert payload["status"] == "COMPLETED"
    assert payload["events"]
    assert payload["topology"]["nodes"]
    assert len(payload["topology"]["nodes"]) == 3  # exactly three agents
    assert [c["key"] for c in payload["topology"]["checkpoints"]] == ["human_approval"]


@pytest.mark.parametrize("fmt", ["json", "markdown", "html"])
def test_report_renders_in_every_format(client, analysed, fmt):
    response = client.get(f"/api/ecr/ECR-2026-001/report?format={fmt}")
    assert response.status_code == 200
    assert len(response.text) > 500


def test_report_rejects_an_unknown_format(client, analysed):
    assert client.get("/api/ecr/ECR-2026-001/report?format=pdf").status_code == 422


def test_dashboard_stats(client, analysed):
    payload = client.get("/api/dashboard/stats").json()
    assert payload["total_ecrs"] >= 13
    assert payload["analysed_ecrs"] >= 1
    assert "risk_distribution" not in payload


def test_agents_catalogue_lists_three_agents(client):
    payload = client.get("/api/agents").json()
    keys = [agent["key"] for agent in payload["agents"]]
    assert keys == ["retrieval_agent", "correlation_agent", "summarization_agent"]
    assert all(agent["steps"] for agent in payload["agents"][:3])


def test_tool_registry_is_populated(client):
    tools = client.get("/api/agents/tools").json()["tools"]
    names = {tool["name"] for tool in tools}
    assert {"semantic_requirement_search", "analyze_changed_files", "comments_for_ecr"} <= names


def test_agent_runs_are_persisted(client, analysed):
    runs = client.get(f"/api/agents/runs?workflow_id={analysed['workflow_id']}").json()
    assert runs
    assert all(run["agent"] for run in runs)


def test_component_graph(client):
    payload = client.get("/api/components/graph").json()
    assert len(payload["nodes"]) == 55
    assert payload["stats"]["edges"] == 72


def test_chat_query_resolves_the_ecr_and_answers(client, analysed):
    payload = client.post(
        "/api/chat/query",
        json={"query": "Analyze ECR-2026-001 and tell me which regression tests to run"},
    ).json()
    assert payload["ecr_id"] == "ECR-2026-001"
    assert payload["intent"] == "TEST_RECOMMENDATION"
    assert payload["answer"]


def test_chat_query_without_an_ecr_asks_for_one(client):
    payload = client.post("/api/chat/query", json={"query": "hello there"}).json()
    assert payload["ecr_id"] is None
    assert "ECR" in payload["answer"]


def test_ask_explains_a_specific_test(client, analysed):
    tests = client.get("/api/ecr/ECR-2026-001/tests?priority=P0").json()["tests"]
    test_id = tests[0]["test_case_id"]
    payload = client.post(
        f"/api/ecr/ECR-2026-001/ask", json={"question": f"Why was {test_id} selected?"}
    ).json()
    assert test_id in payload["focus"]
    assert payload["answer"]


def test_feedback_round_trip(client, analysed):
    created = client.post(
        "/api/feedback",
        json={"ecr_id": "ECR-2026-001", "target_id": "TC-1020", "useful": True},
    ).json()
    assert created["useful"] is True
    assert any(item["target_id"] == "TC-1020" for item in client.get("/api/feedback").json())


def test_approve_rejects_when_not_awaiting(client, analysed):
    response = client.post("/api/ecr/ECR-2026-001/approve", json={"approved": True})
    assert response.status_code == 409
