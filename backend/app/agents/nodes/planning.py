"""Part of the *understand_ecr* step: plan the investigation.

The plan has five fixed steps. Related defects are always gathered and
analysed. What varies is the dependency investigation: a copy tweak on a
profile page does not pay for it, while a schema change does. Every step and
every skipped investigation gets a stated reason.
"""
from __future__ import annotations

from typing import Any

from app.agents.tools.registry import tool
from app.schemas.common import ChangeType

STEPS = ["understand_ecr", "gather_evidence", "assess_impact", "select_tests", "summarize"]

# Change types where the extra investigation is worth its cost
DEPENDENCY_HEAVY = {
    ChangeType.DATABASE.value,
    ChangeType.API.value,
    ChangeType.API_AND_BACKEND.value,
    ChangeType.BACKEND.value,
    ChangeType.INTEGRATION.value,
    ChangeType.SECURITY.value,
    ChangeType.INFRASTRUCTURE.value,
    ChangeType.MIXED.value,
}

HIGH_SIGNAL_INDICATORS = {
    "financial_transaction",
    "schema_migration",
    "authentication_change",
    "shared_library_change",
    "concurrency_change",
}

INVESTIGATION_LABELS = {
    "requirements": "impacted requirements",
    "code_impact": "code impact",
    "historical_defects": "similar historical defects",
    "dependencies": "component dependencies",
    "collaboration_retrieval": "review comments and evidence",
}


@tool("build_plan", "Decide which evidence to gather for this change.")
def build_plan(
    analysis: dict[str, Any],
    options: dict[str, Any],
    retrieval_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    change_type = analysis.get("change_type", ChangeType.MIXED.value)
    acronyms = {"ui": "UI", "api": "API"}
    change_label = " ".join(
        acronyms.get(word, word) for word in change_type.replace("_", " ").lower().split()
    )
    indicators = set(analysis.get("risk_indicators") or [])
    force_full = bool(options.get("force_full_analysis"))

    by_rule = force_full or change_type in DEPENDENCY_HEAVY or bool(indicators & HIGH_SIGNAL_INDICATORS)
    # The Retrieval Agent's LLM may add the dependency walk the rules would skip, never remove it.
    llm_asked = bool((retrieval_plan or {}).get("needs_dependency_check"))
    run_dependency = by_rule or llm_asked

    # Defects are always analysed: even a small change can bring back an old bug.
    investigations = ["requirements", "code_impact", "historical_defects"]
    skipped: list[str] = []
    reasons: dict[str, str] = {}

    if run_dependency:
        investigations.append("dependencies")
        if not by_rule:
            reasons["dependencies"] = "Requested by the Retrieval Agent's LLM review: " + (
                (retrieval_plan or {}).get("dependency_reason") or "the change may reach other components."
            )
    else:
        skipped.append("dependencies")
        reasons["dependencies"] = "The change stays inside a single presentation component."
    investigations.append("collaboration_retrieval")

    reasons.update(
        {
            "understand_ecr": "Classifies the change and decides which evidence is worth gathering.",
            "gather_evidence": "Collects "
            + ", ".join(INVESTIGATION_LABELS[key] for key in investigations)
            + ".",
            "assess_impact": "Works out which components the change touches directly and which it reaches through dependencies.",
            "select_tests": "Keeps only the regression tests that matter, orders them by priority and "
            "checks whether each related defect could happen again.",
            "summarize": "Answers in plain language, summarises the defects and publishes the report.",
        }
    )

    base = change_label[:1].upper() + change_label[1:]
    if force_full:
        routing = "Full analysis was requested, so all evidence is gathered."
    elif not skipped:
        routing = f"{base} with {len(indicators)} risk indicator(s) detected. Gathering all evidence."
    else:
        routing = (
            f"{base} with {len(indicators)} risk indicator(s) detected. Not needed: "
            + ", ".join(INVESTIGATION_LABELS[key] for key in skipped)
            + "."
        )

    return {
        "plan": list(STEPS),
        "steps": list(STEPS),
        "investigations": investigations,
        "skipped": skipped,
        "reasons": reasons,
        "routing_reason": routing,
        "rationale": [reasons[key] for key in [*STEPS, *skipped]],
        "checkpoint": bool(options.get("human_in_the_loop")),
    }


def planning_step(state: dict[str, Any]) -> dict[str, Any]:
    analysis = state.get("ecr_analysis") or {}
    options = state.get("options") or {}
    decision = build_plan(analysis, options, state.get("retrieval_plan"))

    from app.agents.runtime import registry

    run = registry.get(state.get("workflow_id", ""))
    if run:
        run.plan = list(decision["steps"])
        run.skipped = decision["skipped"]

    return {
        "plan": decision["steps"],
        "plan_detail": {
            "steps": decision["steps"],
            "investigations": decision["investigations"],
            "skipped": decision["skipped"],
            "reasons": decision["reasons"],
            "routing_reason": decision["routing_reason"],
            "approval_checkpoint": decision["checkpoint"],
            "source": "policy",
        },
        "skipped_steps": decision["skipped"],
        "tools_used": {"planning": ["build_plan"]},
        "_confidence": 0.95,
        "_reasoning": decision["routing_reason"],
    }
