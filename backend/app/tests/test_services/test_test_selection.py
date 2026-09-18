"""Regression selection: scoring, banding, filtering and ordering."""
from __future__ import annotations

from app.config import TestSelectionWeights
from app.schemas.common import Priority
from app.services.test_selection_service import (
    SelectionContext,
    TestSelectionEngine,
    priority_distribution,
)


def make_test(**overrides):
    base = {
        "test_case_id": "TC-9001",
        "title": "Validate payment with a supported currency",
        "description": "",
        "feature": "Multi Currency Processing",
        "suite": "Payments Regression",
        "component": "CMP-005",
        "linked_components": ["CMP-005", "CMP-003"],
        "requirement_id": "REQ-1004",
        "automation_status": "AUTOMATED",
        "average_execution_time": 60.0,
        "historical_failure_rate": 0.2,
        "tags": [],
    }
    base.update(overrides)
    return base


def context(**overrides):
    base = dict(
        matched_requirements={"REQ-1004": 95.0},
        direct_components={"CMP-005"},
        indirect_components={"CMP-006"},
        dependency_distance={"CMP-006": 1},
        propagation={"CMP-006": 0.7},
        component_criticality={"CMP-005": "HIGH", "CMP-006": "HIGH"},
        defect_components={"CMP-005"},
        semantic_scores={"TC-9001": 90.0},
        affected_features={"Multi Currency Processing"},
    )
    base.update(overrides)
    return SelectionContext(**base)


def test_directly_relevant_test_scores_high():
    scored = TestSelectionEngine().score_test(make_test(), context())
    assert scored.relevance_score >= 90
    assert scored.priority is Priority.P0
    assert scored.selected


def test_unrelated_test_is_dropped():
    unrelated = make_test(
        test_case_id="TC-9999",
        requirement_id="REQ-9999",
        component="CMP-013",
        linked_components=["CMP-013"],
        feature="Reporting",
        historical_failure_rate=0.0,
    )
    scored = TestSelectionEngine().score_test(unrelated, context(semantic_scores={}))
    assert scored.relevance_score < 50
    assert not scored.selected
    assert scored.priority is Priority.P3


def test_breakdown_sums_to_the_relevance_score():
    scored = TestSelectionEngine().score_test(make_test(), context())
    parts = sum(scored.breakdown.model_dump().values())
    assert round(parts, 1) == round(scored.relevance_score, 1)


def test_every_selected_test_explains_itself():
    scored = TestSelectionEngine().score_test(make_test(), context())
    assert scored.reasons
    assert "REQ-1004" in scored.reason or "relevance" in scored.reason.lower()


def test_selection_respects_the_threshold_and_the_cap():
    tests = [make_test(test_case_id=f"TC-90{index:02d}") for index in range(10)]
    engine = TestSelectionEngine(threshold=95.0)
    selected, rejected = engine.select(tests, context(), max_tests=3)
    assert len(selected) <= 3
    assert all(test.relevance_score >= 95.0 for test in selected)
    assert all(not test.selected for test in rejected)


def test_weights_are_configurable():
    only_semantic = TestSelectionWeights(
        requirement_match=0.0,
        component_match=0.0,
        dependency_relevance=0.0,
        historical_failure=0.0,
        semantic_similarity=1.0,
    )
    scored = TestSelectionEngine(weights=only_semantic).score_test(make_test(), context())
    assert scored.breakdown.requirement_match == 0.0
    assert round(scored.relevance_score) == round(scored.breakdown.semantic_similarity)


def test_prioritisation_orders_p0_first_then_by_runtime():
    engine = TestSelectionEngine()
    slow = engine.score_test(make_test(test_case_id="TC-SLOW", average_execution_time=300.0), context())
    fast = engine.score_test(make_test(test_case_id="TC-FAST", average_execution_time=30.0), context())
    weak = engine.score_test(
        make_test(
            test_case_id="TC-WEAK",
            requirement_id="REQ-0000",
            component="CMP-006",
            linked_components=["CMP-006"],
            historical_failure_rate=0.0,
        ),
        context(semantic_scores={}),
    )
    ordered = engine.prioritise([slow, weak, fast], context())
    assert ordered[0].test_case_id == "TC-FAST"  # same band, quickest feedback first
    assert ordered[-1].test_case_id == "TC-WEAK"
    assert [test.execution_order for test in ordered] == [1, 2, 3]


def test_priority_distribution_counts_every_band():
    engine = TestSelectionEngine()
    scored = [engine.score_test(make_test(), context())]
    distribution = priority_distribution(scored)
    assert set(distribution) == {"P0", "P1", "P2", "P3"}
    assert sum(distribution.values()) == 1
