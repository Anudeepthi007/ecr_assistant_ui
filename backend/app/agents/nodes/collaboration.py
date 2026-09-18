"""Retrieval step: review comments and evidence artefacts.

This is the step that replaces "scroll through every comment thread and
evidence folder to work out what was decided".
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from app.agents.tools.collaboration_tools import (
    comments_for_ecr,
    evidence_for_ecr,
    evidence_gaps,
    extract_comment_signals,
)
from app.agents.nodes.scope import is_scoped
from app.database import session_scope
from app.llm.provider import get_llm


def collaboration_step(state: dict[str, Any]) -> dict[str, Any]:
    ecr_id = state.get("ecr_id", "")
    requirements = state.get("requirements") or []
    defects = state.get("defects") or []
    related_ids = [
        *(r.get("requirement_id") for r in requirements),
        *(d.get("defect_id") for d in defects),
        ecr_id,
    ]
    if is_scoped(state.get("ecr_input")):
        related_ids = [ecr_id]  # a record with its own scope: only what is attached to it

    with session_scope() as db:
        comments = comments_for_ecr(db, ecr_id, related_ids=related_ids)
        evidence = evidence_for_ecr(db, ecr_id, related_ids=related_ids)

    signals = extract_comment_signals(comments)
    gaps = evidence_gaps(evidence, [r.get("requirement_id", "") for r in requirements])
    outcomes = Counter(item.get("outcome", "") for item in evidence)
    concerns = [c for c in comments if c.get("sentiment") == "CONCERN"]

    confidence = round(
        min(0.95, 0.45 + 0.25 * bool(comments) + 0.2 * bool(evidence) + 0.05 * bool(signals["decisions"])),
        3,
    )
    baseline = (
        f"Collected {len(comments)} comment(s) and {len(evidence)} evidence artefact(s) for {ecr_id}. "
        f"{len(signals['decisions'])} explicit decision(s), {len(concerns)} raised concern(s). "
        + (
            f"Evidence outcomes: {', '.join(f'{k} x{v}' for k, v in outcomes.items() if k)}. "
            if outcomes
            else "No evidence outcomes recorded. "
        )
        + (
            f"{len(gaps)} impacted requirement(s) have no evidence attached."
            if gaps
            else "Every impacted requirement has at least one evidence artefact."
        )
    )
    reasoning = get_llm().narrate(
        task="Summarise what the team has already decided and flagged on this change",
        context={
            "decisions": signals["decisions"][:4],
            "risks": signals["risks"][:4],
            "scope": signals["scope"][:3],
            "evidence": [
                {"id": e["evidence_id"], "title": e["title"], "outcome": e["outcome"]}
                for e in evidence[:5]
            ],
        },
        fallback=baseline,
    )

    return {
        "comments": comments,
        "evidence": evidence,
        "collaboration_analysis": {
            "comment_count": len(comments),
            "evidence_count": len(evidence),
            "signals": signals,
            "evidence_outcomes": {k: v for k, v in outcomes.items() if k},
            "evidence_gaps": gaps,
            "open_concerns": [
                {"comment_id": c["comment_id"], "author": c["author"], "text": c["body"]}
                for c in concerns
            ],
            "confidence": confidence,
            "reasoning": reasoning,
        },
        "tools_used": {
            "collaboration_retrieval": [
                "comments_for_ecr",
                "evidence_for_ecr",
                "extract_comment_signals",
                "evidence_gaps",
            ]
        },
        "_confidence": confidence,
        "_reasoning": reasoning,
        "_summary": {
            "comments": len(comments),
            "evidence": len(evidence),
            "decisions": len(signals["decisions"]),
            "concerns": len(concerns),
        },
    }
