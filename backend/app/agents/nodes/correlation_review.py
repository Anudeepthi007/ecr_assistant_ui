"""Part of the *select_tests* step: the Correlation Agent's LLM reviews the bundle.

The graph in :mod:`correlation` records *which* artefacts are linked. It cannot
see that a reviewer's concern contradicts a passing test run, or that a defect
likely to return has no evidence. The model reads the whole correlated bundle
and reports the links that matter, the contradictions and the gaps - the
joining-up a person would otherwise do by hand across five sources.

Guardrails: every identifier the model cites must exist in the bundle (unknown
ones are dropped, and a finding left with none is discarded), and nothing it
says changes a score, a test selection or a recurrence rating. The
Summarization Agent receives the findings to explain.
"""
from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from pydantic import BaseModel, Field

from app.llm.provider import get_llm
from app.prompts import CORRELATION_SYSTEM_PROMPT, CORRELATION_TASK

MAX_FINDINGS = 6
LLM_FINDINGS = 4  # per list, so the model's reply fits the token limit
PASSING = {"PASS", "PASSED", "APPROVED", "SUCCESS"}


class Finding(BaseModel):
    ids: list[str] = Field(default_factory=list)
    text: str = ""


class CorrelationReview(BaseModel):
    summary: str = ""
    key_links: list[Finding] = Field(default_factory=list)
    conflicts: list[Finding] = Field(default_factory=list)
    gaps: list[Finding] = Field(default_factory=list)
    source: str = "llm"


def _selected_tests(state: dict[str, Any]) -> list[dict[str, Any]]:
    return state.get("selected_tests") or (state.get("test_selection") or {}).get("selected_tests") or []


def _known_ids(state: dict[str, Any]) -> set[str]:
    impact = state.get("impact_analysis") or {}
    ids = {
        state.get("ecr_id", ""),
        *(r["requirement_id"] for r in state.get("requirements") or []),
        *(d["defect_id"] for d in state.get("defects") or []),
        *(t["test_case_id"] for t in _selected_tests(state)),
        *(c["comment_id"] for c in state.get("comments") or []),
        *(e["evidence_id"] for e in state.get("evidence") or []),
        *(
            c["component_id"]
            for c in [
                *(impact.get("directly_impacted_components") or []),
                *(impact.get("indirectly_impacted_components") or []),
            ]
        ),
    }
    ids.discard("")
    return ids


def _rule_review(state: dict[str, Any]) -> CorrelationReview:
    """What the rules alone can say. Used when the LLM is unavailable, and as its starting point."""
    correlation = state.get("correlation") or {}
    collaboration = state.get("collaboration_analysis") or {}
    insights = state.get("defect_insights") or {}

    key_links = [
        Finding(
            ids=[item["artefact"]],
            text=f"{item['artefact']} is backed by {item['source_count']} separate sources "
            f"({', '.join(item['sources'])}).",
        )
        for item in (correlation.get("corroborated") or [])[:4]
    ]

    passing: dict[str, list[str]] = defaultdict(list)
    for item in state.get("evidence") or []:
        if item.get("target_id") and str(item.get("outcome", "")).upper() in PASSING:
            passing[item["target_id"]].append(item["evidence_id"])
    conflicts: list[Finding] = []
    for comment in state.get("comments") or []:
        if comment.get("sentiment") != "CONCERN":
            continue
        for target in [comment.get("target_id"), *(comment.get("references") or [])]:
            runs = passing.get(target or "")
            if runs:
                conflicts.append(
                    Finding(
                        ids=[comment["comment_id"], target, *runs[:2]],
                        text=f"{comment.get('author') or 'A reviewer'} raised a concern about {target} "
                        f"({comment['comment_id']}), but {', '.join(runs[:2])} recorded a pass. "
                        "Check that the evidence really covers the concern.",
                    )
                )
                break

    gaps = [
        Finding(ids=[rid], text=f"{rid} is impacted by this change but has no evidence attached.")
        for rid in (collaboration.get("evidence_gaps") or [])[:4]
    ]
    gaps += [
        Finding(
            ids=[row["defect_id"]],
            text=f"{row['defect_id']} could happen again and no recommended test covers it.",
        )
        for row in insights.get("defects") or []
        if row.get("chance_of_recurrence") == "High" and not row.get("covered")
    ][:4]

    summary = (
        f"{len(key_links)} artefact(s) are confirmed by more than one source, "
        f"{len(conflicts)} contradiction(s) and {len(gaps)} gap(s) were found."
    )
    return CorrelationReview(
        summary=summary,
        key_links=key_links[:MAX_FINDINGS],
        conflicts=conflicts[:MAX_FINDINGS],
        gaps=gaps[:MAX_FINDINGS],
        source="rules",
    )


def _bundle(state: dict[str, Any]) -> dict[str, Any]:
    impact = state.get("impact_analysis") or {}
    insights = {row["defect_id"]: row for row in (state.get("defect_insights") or {}).get("defects") or []}
    return {
        "ecr": {
            "id": state.get("ecr_id"),
            "title": (state.get("ecr_input") or {}).get("title"),
            "description": (state.get("ecr_input") or {}).get("description"),
        },
        "requirements": [
            {"id": r["requirement_id"], "title": r.get("title"), "relevance": r.get("relevance")}
            for r in (state.get("requirements") or [])[:10]
        ],
        "recommended_tests": [
            {
                "id": t["test_case_id"],
                "title": t.get("title"),
                "priority": t.get("priority"),
                "requirement": t.get("requirement_id"),
            }
            for t in _selected_tests(state)[:15]
        ],
        "past_defects": [
            {
                "id": d["defect_id"],
                "title": d.get("title"),
                "component": d.get("affected_component"),
                "chance_it_happens_again": (insights.get(d["defect_id"]) or {}).get("chance_of_recurrence"),
                "covered_by_tests": (insights.get(d["defect_id"]) or {}).get("covering_tests", []),
            }
            for d in (state.get("defects") or [])[:8]
        ],
        "comments": [
            {
                "id": c["comment_id"],
                "author": c.get("author"),
                "type": c.get("category"),
                "sentiment": c.get("sentiment"),
                "on": c.get("target_id"),
                "references": c.get("references") or [],
                "text": str(c.get("body", ""))[:280],
            }
            for c in (state.get("comments") or [])[:12]
        ],
        "evidence": [
            {
                "id": e["evidence_id"],
                "title": e.get("title"),
                "type": e.get("evidence_type"),
                "outcome": e.get("outcome"),
                "on": e.get("target_id"),
            }
            for e in (state.get("evidence") or [])[:10]
        ],
        "impacted_components": [
            {"id": c["component_id"], "name": c.get("name"), "impact": c.get("impact_type")}
            for c in [
                *(impact.get("directly_impacted_components") or []),
                *(impact.get("indirectly_impacted_components") or []),
            ][:10]
        ],
    }


def _grounded(findings: list[Finding], known: set[str]) -> list[dict[str, Any]]:
    kept = []
    for finding in findings:
        ids = [i for i in dict.fromkeys(finding.ids) if i in known]
        text = " ".join(finding.text.split())
        if ids and text:
            kept.append({"ids": ids, "text": text[:400]})
    return kept[:MAX_FINDINGS]


def correlation_review_step(state: dict[str, Any]) -> dict[str, Any]:
    rules = _rule_review(state)
    review = rules

    llm = get_llm()
    if not llm.is_mock:
        review = llm.generate_structured(
            CORRELATION_TASK.format(
                bundle=json.dumps(_bundle(state), default=str)[:12000],
                rule_findings=json.dumps(rules.model_dump(exclude={"source"})),
                max_findings=LLM_FINDINGS,
            ),
            CorrelationReview,
            system=CORRELATION_SYSTEM_PROMPT,
            fallback=rules.model_dump(),
        )

    used_llm = review.source != "rules"
    known = _known_ids(state)
    key_links = _grounded(review.key_links, known)
    conflicts = _grounded(review.conflicts, known)
    gaps = _grounded(review.gaps, known)
    if used_llm and not (key_links or conflicts or gaps):
        # Everything the model cited was ungrounded: keep the rule findings instead.
        used_llm = False
        key_links, conflicts, gaps = (
            _grounded(rules.key_links, known),
            _grounded(rules.conflicts, known),
            _grounded(rules.gaps, known),
        )
        review = rules

    reasoning = (
        f"{'The LLM' if used_llm else 'Rule-based'} review of the correlated bundle found "
        f"{len(key_links)} key link(s), {len(conflicts)} contradiction(s) and {len(gaps)} gap(s)."
    )
    return {
        "correlation_review": {
            "source": "llm" if used_llm else "rules",
            "summary": " ".join(review.summary.split()),
            "key_links": key_links,
            "conflicts": conflicts,
            "gaps": gaps,
        },
        "tools_used": {"correlation_review": ["llm.review_correlation"] if used_llm else ["rule_review"]},
        "_reasoning": reasoning,
    }
