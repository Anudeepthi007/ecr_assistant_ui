"""Explainable regression test selection and prioritisation.

Relevance (0-100) per test:

    0.30 requirement match
  + 0.25 component match
  + 0.15 dependency relevance
  + 0.15 historical failure probability
  + 0.15 semantic similarity

Weights come from ``TEST_WEIGHT_*``. Tests scoring below
``TEST_SELECTION_THRESHOLD`` are excluded, the rest are banded
P0 (>=90) / P1 (>=75) / P2 (>=50) / P3.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from app.config import settings
from app.schemas.common import Priority
from app.schemas.test_case import (
    SelectedTest,
    TestCaseRead,
    TestScoreBreakdown,
)

CRITICALITY_INDEX = {"CRITICAL": 1.0, "HIGH": 0.75, "MEDIUM": 0.45, "LOW": 0.2}


@dataclass(slots=True)
class SelectionContext:
    """Impact facts the selection algorithm scores tests against."""

    matched_requirements: dict[str, float] = field(default_factory=dict)  # req -> relevance 0..100
    direct_components: set[str] = field(default_factory=set)
    indirect_components: set[str] = field(default_factory=set)
    dependency_distance: dict[str, int] = field(default_factory=dict)  # component -> hops
    propagation: dict[str, float] = field(default_factory=dict)  # component -> 0..1
    component_criticality: dict[str, str] = field(default_factory=dict)
    defect_components: set[str] = field(default_factory=set)
    semantic_scores: dict[str, float] = field(default_factory=dict)  # test id -> 0..100
    affected_features: set[str] = field(default_factory=set)
    listed_tests: set[str] = field(default_factory=set)  # affected test cases named on the ECR


class TestSelectionEngine:
    def __init__(self, weights=None, threshold: float | None = None) -> None:
        self.weights = weights or settings.test_weights
        self.threshold = threshold if threshold is not None else settings.test_selection_threshold

    # -- individual factors (0..1) ----------------------------------------
    def requirement_factor(self, test: dict[str, Any], ctx: SelectionContext) -> tuple[float, str]:
        relevance = ctx.matched_requirements.get(test.get("requirement_id", ""), 0.0)
        if relevance:
            return min(1.0, relevance / 100.0), (
                f"covers impacted requirement {test['requirement_id']} "
                f"({relevance:.0f}% relevance)"
            )
        if test.get("feature") in ctx.affected_features:
            return 0.45, f"exercises affected feature '{test.get('feature')}'"
        return 0.0, ""

    def component_factor(self, test: dict[str, Any], ctx: SelectionContext) -> tuple[float, str]:
        component = test.get("component", "")
        linked = set(test.get("linked_components") or [])
        if component in ctx.direct_components:
            return 1.0, f"targets directly modified component {component}"
        if linked & ctx.direct_components:
            hit = sorted(linked & ctx.direct_components)[0]
            return 0.7, f"touches directly modified component {hit}"
        if component in ctx.indirect_components:
            return 0.55, f"targets indirectly impacted component {component}"
        if linked & ctx.indirect_components:
            return 0.35, "touches an indirectly impacted component"
        return 0.0, ""

    def dependency_factor(self, test: dict[str, Any], ctx: SelectionContext) -> tuple[float, str]:
        component = test.get("component", "")
        candidates = [component, *(test.get("linked_components") or [])]
        best = 0.0
        reason = ""
        for candidate in candidates:
            propagation = ctx.propagation.get(candidate, 0.0)
            if propagation > best:
                best = propagation
                distance = ctx.dependency_distance.get(candidate, 0)
                reason = (
                    f"{candidate} is {distance} dependency hop(s) from the change "
                    f"(propagation {propagation:.2f})"
                )
            if candidate in ctx.direct_components and best < 1.0:
                best = 1.0
                reason = f"{candidate} is at the centre of the change"
        return best, reason

    def historical_factor(self, test: dict[str, Any], ctx: SelectionContext) -> tuple[float, str]:
        rate = float(test.get("historical_failure_rate", 0.0) or 0.0)
        value = min(1.0, rate / 0.30)
        reason = ""
        if rate >= 0.15:
            reason = f"historically fails in {rate * 100:.0f}% of runs"
        component = test.get("component", "")
        if component in ctx.defect_components:
            value = min(1.0, value + 0.35)
            reason = (reason + "; " if reason else "") + (
                f"{component} has related historical defects"
            )
        return value, reason

    def semantic_factor(self, test: dict[str, Any], ctx: SelectionContext) -> tuple[float, str]:
        score = ctx.semantic_scores.get(test.get("test_case_id", ""), 0.0)
        value = min(1.0, score / 100.0)
        reason = f"semantic similarity to the change description {score:.0f}%" if score >= 45 else ""
        return value, reason

    # -- scoring ----------------------------------------------------------
    def score_test(self, test: dict[str, Any], ctx: SelectionContext) -> SelectedTest:
        req_v, req_r = self.requirement_factor(test, ctx)
        cmp_v, cmp_r = self.component_factor(test, ctx)
        dep_v, dep_r = self.dependency_factor(test, ctx)
        his_v, his_r = self.historical_factor(test, ctx)
        sem_v, sem_r = self.semantic_factor(test, ctx)

        breakdown = TestScoreBreakdown(
            requirement_match=round(100 * self.weights.requirement_match * req_v, 1),
            component_match=round(100 * self.weights.component_match * cmp_v, 1),
            dependency_relevance=round(100 * self.weights.dependency_relevance * dep_v, 1),
            historical_failure=round(100 * self.weights.historical_failure * his_v, 1),
            semantic_similarity=round(100 * self.weights.semantic_similarity * sem_v, 1),
        )
        score = round(
            breakdown.requirement_match
            + breakdown.component_match
            + breakdown.dependency_relevance
            + breakdown.historical_failure
            + breakdown.semantic_similarity,
            1,
        )
        reasons = [r for r in (req_r, cmp_r, dep_r, his_r, sem_r) if r]
        # A test the ECR names as affected is always kept, whatever it scores.
        listed = test.get("test_case_id") in ctx.listed_tests
        if listed:
            reasons.insert(0, "listed as an affected test case on the ECR")
        payload = {k: v for k, v in test.items() if k in TestCaseRead.model_fields}
        return SelectedTest(
            **payload,
            relevance_score=score,
            priority=Priority.from_score(score),
            breakdown=breakdown,
            reasons=reasons,
            reason=_compose_reason(reasons, score),
            selected=listed or score >= self.threshold,
        )

    def select(
        self,
        tests: Iterable[dict[str, Any]],
        ctx: SelectionContext,
        *,
        max_tests: int | None = None,
    ) -> tuple[list[SelectedTest], list[SelectedTest]]:
        """Return (selected, rejected) scored tests, highest relevance first."""
        scored = [self.score_test(test, ctx) for test in tests]
        scored.sort(key=lambda t: t.relevance_score, reverse=True)
        selected = [t for t in scored if t.selected]
        limit = max_tests if max_tests is not None else settings.max_selected_tests
        if limit and len(selected) > limit:
            for test in selected[limit:]:
                test.selected = False
            selected = selected[:limit]
        rejected = [t for t in scored if not t.selected]
        return selected, rejected

    # -- prioritisation ---------------------------------------------------
    def prioritise(self, tests: list[SelectedTest], ctx: SelectionContext) -> list[SelectedTest]:
        """Order execution by priority first, then fastest feedback.

        Sort key: priority band, then tests the ECR names as affected, then
        criticality of the target component, then relevance, then shortest
        execution time (quick wins first inside a band so failures surface early).
        """
        band_order = {Priority.P0: 0, Priority.P1: 1, Priority.P2: 2, Priority.P3: 3}

        def sort_key(test: SelectedTest):
            criticality = CRITICALITY_INDEX.get(
                ctx.component_criticality.get(test.component, "MEDIUM"), 0.45
            )
            return (
                band_order[test.priority],
                test.test_case_id not in ctx.listed_tests,
                -criticality,
                -test.relevance_score,
                test.average_execution_time,
            )

        ordered = sorted(tests, key=sort_key)
        for index, test in enumerate(ordered, start=1):
            test.execution_order = index
        return ordered


def _compose_reason(reasons: list[str], score: float) -> str:
    if not reasons:
        return "Retained for baseline coverage of the impacted area."
    head = reasons[0][0].upper() + reasons[0][1:]
    tail = "; ".join(reasons[1:3])
    sentence = head + ("; " + tail if tail else "")
    return f"{sentence}. Relevance {score:.0f}%."


def priority_distribution(tests: list[SelectedTest]) -> dict[str, int]:
    distribution = {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
    for test in tests:
        distribution[test.priority.value] += 1
    return distribution


def get_selection_engine() -> TestSelectionEngine:
    return TestSelectionEngine()
