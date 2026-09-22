"""Natural-language interface over the correlated ECR data.

Intent detection is deliberately deterministic (a regex for the ECR number plus
verb matching): routing a user to the wrong ECR is worse than asking them to be
explicit. Once an ECR is resolved, the answer is generated strictly from the
correlated bundle, with citations.
"""
from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy.orm import Session

from app.agents.nodes.summarization import build_answer_context
from app.prompts import ANSWER_SYSTEM_PROMPT, CHAT_FOCUS, CHAT_TASK
from app.agents.runtime import registry
from app.llm.provider import get_llm
from app.logging import get_logger
from app.services import ecr_service
from app.services.rag_service import get_rag_service
from app.vectorstore import COLLECTION_ECRS

logger = get_logger("ecr.chat")

# ECR-2026-001 as well as short ids such as ECR-1
ECR_ID_RE = re.compile(r"\b(ECR[- ]?\d{1,6}(?:[- ]\d{1,6})?)\b", re.IGNORECASE)
# L2R26:TC1 (test ids from the export) before the plain identifier forms
ARTIFACT_RE = re.compile(
    r"\b(L2R\d{1,6}:\s?TC\d{1,4}|(?:REQ|BUG|TC|CMT|EV|PTC|L2R)[- ]?\d{2,6})\b", re.IGNORECASE
)

ANALYZE_VERBS = ("analyz", "analys", "run ", "assess", "impact of", "evaluate")
TEST_VERBS = ("test", "regression", "suite", "execute", "p0", "p1")
WHY_VERBS = ("why", "reason", "justif", "explain")


def detect_intent(query: str) -> dict[str, Any]:
    lowered = query.lower()
    ecr_match = ECR_ID_RE.search(query)
    ecr_id = None
    if ecr_match:
        digits = re.split(r"[- ]", re.sub(r"^ECR[- ]?", "", ecr_match.group(1).upper()))
        ecr_id = "ECR-" + "-".join(part for part in digits if part)
    artifacts = [
        m.group(1).upper().replace(" ", "") if ":" in m.group(1) else m.group(1).upper().replace(" ", "-")
        for m in ARTIFACT_RE.finditer(query)
    ]

    if any(verb in lowered for verb in WHY_VERBS) and artifacts:
        intent = "EXPLAIN_ARTIFACT"
    elif any(verb in lowered for verb in TEST_VERBS):
        intent = "TEST_RECOMMENDATION"
    elif any(verb in lowered for verb in ANALYZE_VERBS):
        intent = "ANALYZE"
    elif ecr_id:
        intent = "QUESTION"
    else:
        intent = "SEARCH"
    return {"intent": intent, "ecr_id": ecr_id, "artifacts": artifacts}


def resolve_ecr(db: Session, query: str, ecr_id: str | None) -> str | None:
    """Explicit id wins; otherwise fall back to semantic search over ECRs."""
    if ecr_id:
        try:
            return ecr_service.get_ecr(db, ecr_id).ecr_id
        except ecr_service.ECRNotFound:
            return None
    hits = get_rag_service().retrieve(COLLECTION_ECRS, query, k=1, min_relevance=35)
    return hits[0].id if hits else None


def _bundle_for(ecr_id: str) -> dict[str, Any] | None:
    run = registry.latest_for_ecr(ecr_id)
    if run and run.state:
        return run.state
    return None


def answer_question(
    db: Session, question: str, *, ecr_id: str | None = None, run_if_missing: bool = True
) -> dict[str, Any]:
    """Answer a question about an ECR from its correlated bundle."""
    detection = detect_intent(question)
    resolved = resolve_ecr(db, question, ecr_id or detection["ecr_id"])
    if not resolved:
        return {
            "answer": (
                "I could not work out which ECR you mean. Give me an ECR number "
                "(for example ECR-2026-001) and I will pull its requirements, defects, "
                "comments, evidence and recommended tests."
            ),
            "intent": detection["intent"],
            "ecr_id": None,
            "citations": [],
            "analysis_available": False,
        }

    state = _bundle_for(resolved)
    if state is None and run_if_missing:
        logger.info("chat.analysis_missing", ecr_id=resolved)
        run = ecr_service.start_analysis(
            db, resolved, {"human_in_the_loop": False, "question": question}, background=False
        )
        state = run.state
    if state is None:
        return {
            "answer": f"{resolved} has not been analysed yet. Run an analysis first.",
            "intent": detection["intent"],
            "ecr_id": resolved,
            "citations": [],
            "analysis_available": False,
        }

    context = build_answer_context(state)
    focus = _focus_context(state, detection)
    llm = get_llm()
    if llm.is_mock:
        answer = _deterministic_answer(state, detection, focus)
    else:
        baseline = _deterministic_answer(state, detection, focus)
        answer = llm.generate(
            CHAT_TASK.format(
                question=question,
                ecr_id=resolved,
                bundle=json.dumps(context, indent=2, default=str)[:12000],
                focus=(
                    CHAT_FOCUS.format(focus=json.dumps(focus, indent=2, default=str)[:4000])
                    if focus
                    else ""
                ),
            ),
            system=ANSWER_SYSTEM_PROMPT,
            max_tokens=800,
            temperature=0.2,
            fallback=baseline,
        ).strip() or baseline

    citations = sorted(
        {
            *detection["artifacts"],
            *(r["id"] for r in context["requirements"][:5]),
            *(t["id"] for t in context["tests"]["top"][:5]),
            *(d["id"] for d in context["historical_defects"][:3]),
        }
    )
    return {
        "answer": answer,
        "intent": detection["intent"],
        "ecr_id": resolved,
        "citations": citations,
        "focus": focus,
        "analysis_available": True,
        "workflow_id": state.get("workflow_id"),
    }


def _focus_context(state: dict[str, Any], detection: dict[str, Any]) -> dict[str, Any]:
    """Pull the exact artifacts the question names (e.g. 'why was TC-1042 selected?')."""
    wanted = set(detection["artifacts"])
    if not wanted:
        return {}
    focus: dict[str, Any] = {}
    for test in state.get("selected_tests") or []:
        if test["test_case_id"] in wanted:
            focus[test["test_case_id"]] = {
                "title": test["title"],
                "priority": test["priority"],
                "relevance": test["relevance_score"],
                "why_selected": test["reason"],
                "score_breakdown": test["breakdown"],
                "requirement": test["requirement_id"],
                "component": test["component"],
            }
    for requirement in state.get("requirements") or []:
        if requirement["requirement_id"] in wanted:
            focus[requirement["requirement_id"]] = {
                "title": requirement["title"],
                "relevance": requirement["relevance"],
                "matched_via": requirement["match_type"],
                "why": requirement["reason"],
            }
    for defect in state.get("defects") or []:
        if defect["defect_id"] in wanted:
            focus[defect["defect_id"]] = {
                "title": defect["title"],
                "severity": defect["severity"],
                "root_cause": defect["root_cause"],
                "why": defect["reason"],
            }
    for comment in state.get("comments") or []:
        if comment["comment_id"] in wanted:
            focus[comment["comment_id"]] = {
                "author": comment["author"],
                "category": comment["category"],
                "body": comment["body"],
            }
    return focus


def _deterministic_answer(
    state: dict[str, Any], detection: dict[str, Any], focus: dict[str, Any]
) -> str:
    """Rule-based answer used in demo (mock) mode."""
    selection = state.get("test_selection") or {}
    if focus:
        parts = []
        for artifact, detail in focus.items():
            reason = detail.get("why_selected") or detail.get("why") or detail.get("body", "")
            parts.append(f"{artifact}: {reason}")
        return " ".join(parts)
    if detection["intent"] == "TEST_RECOMMENDATION":
        distribution = selection.get("priority_distribution", {})
        top = ", ".join(t["test_case_id"] for t in (selection.get("selected_tests") or [])[:8])
        return (
            f"{len(selection.get('selected_tests') or [])} of {selection.get('total_available')} "
            f"regression tests are recommended ({selection.get('reduction_percentage')}% reduction): "
            f"{distribution.get('P0', 0)} P0, {distribution.get('P1', 0)} P1, "
            f"{distribution.get('P2', 0)} P2, {distribution.get('P3', 0)} P3. "
            f"Start with {top}."
        )
    return state.get("final_answer") or (
        f"The analysis of {state.get('ecr_id')} is ready - ask about its requirements, "
        f"recommended tests or past defects."
    )
