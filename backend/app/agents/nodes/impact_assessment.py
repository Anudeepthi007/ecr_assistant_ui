"""Correlation step: which components the change touches, and what to do about it.

Direct impact comes from the code the change resolves to; indirect impact is
what the dependency walk shows the change actually propagates to. Each
component is listed with the reasons it is in scope, together with concrete
recommended actions. No score is computed here.
"""
from __future__ import annotations

from typing import Any

from app.agents.nodes.scope import is_scoped, linked_requirement_ids
from app.database import session_scope
from app.llm.provider import get_llm
from app.models import Component, Requirement
from app.schemas.impact import ComponentImpact, ImpactAssessment

# Downstream components below this propagation strength are reachable but not
# meaningfully impacted; they stay out of the blast radius and the test scope.
INDIRECT_PROPAGATION_FLOOR = 0.25

CRITICALITY_ORDER = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]

MITIGATION_RULES: list[tuple[str, str]] = [
    (
        "shared_library_change",
        "Version the shared library contract and run the consumer regression packs "
        "(refund and payment) before release.",
    ),
    (
        "schema_migration",
        "Use expand-migrate-contract sequencing: deploy a nullable column, backfill in "
        "batches outside the settlement window, then enforce the constraint.",
    ),
    (
        "financial_transaction",
        "Run the money-movement regression pack and reconcile ledger balances in a "
        "staging dry run before promoting.",
    ),
    (
        "authentication_change",
        "Verify the claim survives token refresh and add an explicit step-up bypass test.",
    ),
    (
        "concurrency_change",
        "Add a concurrent-request test that proves the aggregate lock holds under load.",
    ),
    (
        "third_party_integration",
        "Configure an explicit timeout and a fail-open policy for the vendor call.",
    ),
    (
        "performance_change",
        "Measure the query plan before and after, and assert the job budget in CI.",
    ),
]


def impact_assessment_step(state: dict[str, Any]) -> dict[str, Any]:
    analysis = state.get("ecr_analysis") or {}
    requirement_analysis = state.get("requirement_analysis") or {}
    defect_analysis = state.get("defect_analysis") or {}
    code_impact = state.get("code_impact") or {}
    dependency_analysis = state.get("dependency_analysis") or {}
    skipped = set(state.get("skipped_steps") or [])

    degraded = []
    if not defect_analysis or "historical_defects" in skipped:
        degraded.append("defect_analysis")
    if not dependency_analysis or "dependencies" in skipped:
        degraded.append("dependency_analysis")
    if not code_impact or "code_impact" in skipped:
        degraded.append("code_impact")

    # Direct impact must rest on the strongest evidence available. When the code
    # analyzer actually resolved the changed files, keyword-derived candidates are
    # only guesses about topic - including them turns a copy tweak on a page into
    # a "change to the user service".
    code_resolved = bool(code_impact.get("impacted_services"))
    direct_ids = sorted(
        {
            *(code_impact.get("impacted_services") or []),
            *(dependency_analysis.get("seed_components") or []),
        }
        if code_resolved
        else {
            *(dependency_analysis.get("seed_components") or []),
            *(analysis.get("candidate_components") or []),
        }
    )
    if not direct_ids:
        # Nothing resolved from code or named in the text: the components of the
        # requirements the ECR is explicitly linked to are the next best evidence.
        linked = list((state.get("ecr_input") or {}).get("linked_requirements") or [])
        if linked:
            with session_scope() as db:
                direct_ids = sorted(
                    {
                        row.component
                        for row in db.query(Requirement).filter(Requirement.requirement_id.in_(linked))
                        if row.component
                    }
                )
    propagation = dependency_analysis.get("propagation") or {}
    # Everything downstream is "reachable"; only what the change actually
    # propagates to is *impacted*. Without this floor a two-hop async edge drags
    # an unrelated critical service into the blast radius of a copy tweak.
    candidate_indirect = {
        *(code_impact.get("potentially_impacted_services") or []),
        *(dependency_analysis.get("downstream_components") or []),
    } - set(direct_ids)
    indirect_ids = sorted(
        component_id
        for component_id in candidate_indirect
        if propagation.get(component_id, 1.0) >= INDIRECT_PROPAGATION_FLOOR
    )
    weak_links = sorted(candidate_indirect - set(indirect_ids))

    named_by: dict[str, list[str]] = {}
    ecr = state.get("ecr_input") or {}
    if is_scoped(ecr):
        # A record with its own scope: the component of each linked requirement changes
        # directly, and the other components those requirements name are reached.
        with session_scope() as db:
            rows = db.query(Requirement).filter(
                Requirement.requirement_id.in_(sorted(linked_requirement_ids(ecr)))
            ).all()
        direct_ids = sorted({row.component for row in rows if row.component})
        for row in rows:
            for component_id in row.linked_components or []:
                if component_id not in direct_ids:
                    named_by.setdefault(component_id, []).append(row.requirement_id)
        indirect_ids = sorted(named_by)
        weak_links = []

    with session_scope() as db:
        components = {c.component_id: c.as_dict() for c in db.query(Component).all()}

    distances = dependency_analysis.get("distances") or {}
    defect_components = set(defect_analysis.get("defect_prone_components") or [])

    def build(component_id: str, impact_type: str) -> ComponentImpact:
        meta = components.get(component_id, {})
        reasons: list[str] = []
        if impact_type == "DIRECT":
            reasons.append("Directly modified by this change")
        else:
            hops = distances.get(component_id)
            if hops:
                reasons.append(f"{hops} dependency hop(s) downstream of the change")
            if component_id in named_by:
                reasons.append(f"Named by {', '.join(named_by[component_id])}")
        if component_id in defect_components:
            reasons.append("Has related past defects")
        if meta.get("business_criticality") in ("CRITICAL", "HIGH"):
            reasons.append(f"Business criticality {meta.get('business_criticality')}")
        # How strongly the change reaches this component (100 = changed directly).
        strength = 100.0 if impact_type == "DIRECT" else round(100 * propagation.get(component_id, 0.4), 1)
        return ComponentImpact(
            component_id=component_id,
            name=meta.get("name", component_id),
            type=meta.get("type", "SERVICE"),
            business_criticality=meta.get("business_criticality", "MEDIUM"),
            impact_type=impact_type,
            impact_score=strength,
            distance=0 if impact_type == "DIRECT" else int(distances.get(component_id, 1)),
            reasons=reasons,
        )

    direct = [build(cid, "DIRECT") for cid in direct_ids]
    indirect = sorted(
        (build(cid, "INDIRECT") for cid in indirect_ids),
        key=lambda item: item.impact_score,
        reverse=True,
    )

    matched_requirements = requirement_analysis.get("matched_requirements") or []
    indicators = set(analysis.get("risk_indicators") or [])
    mitigations = [text for indicator, text in MITIGATION_RULES if indicator in indicators]
    for concern in (state.get("collaboration_analysis") or {}).get("open_concerns", [])[:2]:
        mitigations.append(f"Address the open review concern from {concern['author']}.")
    if not mitigations:
        mitigations.append("Run the recommended regression suite and review the results before release.")

    functional = (
        f"{len(matched_requirements)} requirement(s) are in scope, led by "
        f"{matched_requirements[0]['requirement_id']} ({matched_requirements[0]['title']})."
        if matched_requirements
        else "No requirement could be traced to this change; treat scope as unverified."
    )
    technical = (
        f"{len(direct)} component(s) change directly and {len(indirect)} more are reached "
        f"through dependencies."
    )
    peak_criticality = max(
        (c.business_criticality for c in [*direct, *indirect]),
        key=lambda value: CRITICALITY_ORDER.index(value) if value in CRITICALITY_ORDER else 0,
        default="MEDIUM",
    )
    business = f"The most business-critical affected component is rated {peak_criticality}."
    baseline = f"{functional} {technical} {business}"
    summary = get_llm().narrate(
        task="Summarise which parts of the system this change affects",
        context={
            "ecr": state.get("ecr_id"),
            "direct_components": [c.name for c in direct],
            "indirect_components": [c.name for c in indirect],
            "requirements": [r["requirement_id"] for r in matched_requirements[:5]],
            "highest_business_criticality": peak_criticality,
        },
        fallback=baseline,
    )

    confidence = round(min(0.96, 0.9 - 0.12 * len(degraded)), 3)
    assessment = ImpactAssessment(
        directly_impacted_components=direct,
        indirectly_impacted_components=indirect,
        functional_impact=functional,
        technical_impact=technical,
        business_impact=business,
        mitigations=mitigations,
        executive_summary=summary,
        confidence=confidence,
        degraded_inputs=degraded,
        metadata={
            "propagation_floor": INDIRECT_PROPAGATION_FLOOR,
            "weakly_coupled_components": weak_links,
        },
    )
    return {
        "impact_analysis": assessment.model_dump(mode="json"),
        "tools_used": {"impact_assessment": ["component_impact", "llm.narrate"]},
        "_confidence": confidence,
        "_reasoning": baseline,
        "_summary": {
            "direct": [c.component_id for c in direct],
            "indirect": [c.component_id for c in indirect],
        },
    }
