"""Correlation Agent part: analyse the past defects related to this ECR.

For every related defect it answers the questions an engineer otherwise works
out by hand: what went wrong, why it matters for this change, can it happen
again, and which recommended test would catch it. It is deterministic, so the
same ECR always gets the same defect analysis.
"""
from __future__ import annotations

from collections import Counter
from datetime import timezone
from typing import Any

from app.agents.nodes.scope import is_scoped
from app.database import session_scope
from app.models import Component, Defect
from app.models.base import utcnow

CLOSED_STATUSES = {"CLOSED", "RESOLVED", "DONE", "VERIFIED"}


def _days_ago(stamp) -> int | None:
    if stamp is None:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return max(0, (utcnow() - stamp).days)


def component_history(
    defects: list[Defect], ordered_components: list[tuple[str, str]], names: dict[str, str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Defect history of the components the change touches, plus what is open now.

    This is shown even when no past defect matches the change itself, so the
    section always tells the reader how defect-prone the affected area is.
    """
    by_component: dict[str, list[Defect]] = {}
    for defect in defects:
        by_component.setdefault(defect.affected_component, []).append(defect)

    history = []
    for component_id, impact in ordered_components:
        rows = by_component.get(component_id) or []
        if not rows:
            continue
        causes = Counter(d.root_cause_category for d in rows if d.root_cause_category)
        ages = [age for age in (_days_ago(d.detected_at) for d in rows) if age is not None]
        history.append(
            {
                "component": component_id,
                "component_name": names.get(component_id, component_id),
                "impact": impact,
                "total": len(rows),
                "severe": sum(1 for d in rows if d.severity in ("CRITICAL", "HIGH")),
                "open": sum(1 for d in rows if (d.status or "").upper() not in CLOSED_STATUSES),
                "reached_production": sum(1 for d in rows if d.escaped_to_production),
                "last_seen_days": min(ages) if ages else None,
                "top_cause": causes.most_common(1)[0][0] if causes else "",
            }
        )

    touched = {component_id for component_id, _ in ordered_components}
    open_defects = [
        {
            "defect_id": d.defect_id,
            "title": d.title,
            "severity": d.severity,
            "status": d.status,
            "component": d.affected_component,
            "component_name": names.get(d.affected_component, d.affected_component),
            "open_days": _days_ago(d.detected_at),
        }
        for d in defects
        if (d.status or "").upper() not in CLOSED_STATUSES
        and (d.affected_component in touched or touched & set(d.related_components or []))
    ]
    open_defects.sort(key=lambda row: SEVERITY_WEIGHT.get(row["severity"], 0.45), reverse=True)
    return history, open_defects

SEVERITY_WEIGHT = {"CRITICAL": 1.0, "HIGH": 0.75, "MEDIUM": 0.45, "LOW": 0.2}
HIGH_CHANCE = 0.7
MEDIUM_CHANCE = 0.45
MAX_TESTS = 3
CHANCE_ORDER = {"High": 0, "Medium": 1, "Low": 2}


def analyze_defects(
    defects: list[dict[str, Any]],
    *,
    requirement_ids: set[str],
    direct: set[str],
    indirect: set[str],
    selected_tests: list[dict[str, Any]],
    linked_requirements: dict[str, list[str]],
    reopen_counts: dict[str, int],
    component_names: dict[str, str],
) -> list[dict[str, Any]]:
    rows = []
    for defect in defects:
        defect_id = defect["defect_id"]
        component = defect.get("affected_component", "")
        name = component_names.get(component, component)
        requirements = linked_requirements.get(defect_id, [])
        shared_requirements = [r for r in requirements if r in requirement_ids]

        tests = [
            test
            for test in selected_tests
            if (component and test.get("component") == component)
            or (test.get("requirement_id") and test["requirement_id"] in requirements)
        ]
        tests.sort(key=lambda test: test.get("relevance_score", 0), reverse=True)
        test_ids = [test["test_case_id"] for test in tests[:MAX_TESTS]]

        touches = component in direct or component in indirect
        score = (
            0.3 * SEVERITY_WEIGHT.get(defect.get("severity", "MEDIUM"), 0.45)
            + 0.2 * min(1.0, float(defect.get("similarity", 0)) / 100.0)
            + (0.3 if component in direct else 0.15 if component in indirect else 0.0)
            + (0.1 if shared_requirements else 0.0)
            + (0.05 if defect.get("escaped_to_production") else 0.0)
            + min(0.05, 0.025 * reopen_counts.get(defect_id, 0))
        )
        chance = "High" if score >= HIGH_CHANCE else "Medium" if score >= MEDIUM_CHANCE else "Low"
        # A defect can only come back through code this change actually reaches.
        if not touches:
            chance = "Low"

        why = []
        if component in direct:
            why.append(f"This change touches {name}, where the defect happened.")
        elif component in indirect:
            why.append(f"This change indirectly affects {name}, where the defect happened.")
        if shared_requirements:
            why.append(
                f"It broke {', '.join(shared_requirements)}, which this ECR also affects"
                + ("." if touches else ", but the change does not touch the code where it happened.")
            )
        if not why:
            why.append("Its description is similar to this change, but the change does not touch its code.")
        if defect.get("escaped_to_production"):
            why.append("It reached production last time.")

        cause = (defect.get("root_cause") or defect.get("title") or "").rstrip(".")
        if test_ids:
            check = f"Run {', '.join(test_ids)} to make sure it does not come back."
        elif chance == "Low":
            check = "Low chance with this change. No extra check needed."
        else:
            check = f"No recommended test covers this. Check that the fix still holds: {cause}."

        rows.append(
            {
                "defect_id": defect_id,
                "title": defect.get("title", ""),
                "severity": defect.get("severity", "MEDIUM"),
                "status": defect.get("status", ""),
                "component": component,
                "component_name": name,
                "root_cause": defect.get("root_cause", ""),
                "root_cause_category": defect.get("root_cause_category", ""),
                "similarity": defect.get("similarity", 0),
                "why_it_matters": " ".join(why),
                "chance_of_recurrence": chance,
                "covering_tests": test_ids,
                "covered": bool(test_ids),
                "what_to_check": check,
            }
        )
    rows.sort(
        key=lambda row: (
            CHANCE_ORDER[row["chance_of_recurrence"]],
            -SEVERITY_WEIGHT.get(row["severity"], 0.45),
            -float(row["similarity"] or 0),
        )
    )
    return rows


def defect_insights_step(state: dict[str, Any]) -> dict[str, Any]:
    defects = state.get("defects") or []
    impact = state.get("impact_analysis") or {}
    direct = {c["component_id"]: c["name"] for c in impact.get("directly_impacted_components") or []}
    indirect = {c["component_id"]: c["name"] for c in impact.get("indirectly_impacted_components") or []}
    selected = (state.get("test_selection") or {}).get("selected_tests") or []

    defect_ids = {d["defect_id"] for d in defects}
    linked: dict[str, list[str]] = {}
    reopened: dict[str, int] = {}
    names: dict[str, str] = {}
    ordered = [(c, "Direct") for c in direct] + [(c, "Indirect") for c in indirect if c not in direct]
    with session_scope() as db:
        names = {row.component_id: row.name for row in db.query(Component)}
        all_defects = db.query(Defect).all()
        for row in all_defects:
            if row.defect_id in defect_ids:
                linked[row.defect_id] = list(row.linked_requirements or [])
                reopened[row.defect_id] = int(row.reopen_count or 0)
        history, open_defects = component_history(all_defects, ordered, names)
    scoped = is_scoped(state.get("ecr_input"))
    if scoped:  # only this record's own defects, not the components' whole history
        history = []
        open_defects = [row for row in open_defects if row["defect_id"] in defect_ids]
    names.update(indirect)
    names.update(direct)

    rows = analyze_defects(
        defects,
        requirement_ids={r["requirement_id"] for r in state.get("requirements") or []},
        direct=set(direct),
        indirect=set(indirect),
        selected_tests=selected,
        linked_requirements=linked,
        reopen_counts=reopened,
        component_names=names,
    )
    chances = Counter(row["chance_of_recurrence"] for row in rows)
    causes = Counter(row["root_cause_category"] for row in rows if row["root_cause_category"])
    # Only defects that could realistically come back need a manual check.
    not_covered = [
        row["defect_id"] for row in rows if not row["covered"] and row["chance_of_recurrence"] != "Low"
    ]
    insights = {
        "defects": rows,
        "total": len(rows),
        "high": chances["High"],
        "medium": chances["Medium"],
        "low": chances["Low"],
        "not_covered": not_covered,
        "common_causes": [cause for cause, _ in causes.most_common(3)],
        "component_history": history,
        "scoped": scoped,
        "open_defects": open_defects,
    }
    reasoning = (
        f"Analysed {len(rows)} related defect(s): {chances['High']} could come back with this change, "
        f"{len(not_covered)} not covered by the recommended tests."
    )
    return {
        "defect_insights": insights,
        "tools_used": {"defect_insights": ["analyze_defects"]},
        "_confidence": 0.9 if rows else 0.75,
        "_reasoning": reasoning,
    }
