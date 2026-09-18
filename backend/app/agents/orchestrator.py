"""LangGraph orchestrator.

    START -> retrieval_agent -> correlation_agent
          -> (approval gate) -> [human_approval] -> summarization_agent -> END

The gate is a real conditional edge: the approval checkpoint is only entered
when the user ticks "Require approval" for the run. The checkpoint blocks on the run registry, so the API can
resume it with an approve/reject decision.
"""
from __future__ import annotations

import time
from functools import lru_cache
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.agents.nodes.agents import correlation_agent, retrieval_agent, summarization_agent
from app.agents.runtime import emit_event, registry
from app.agents.state import ECRWorkflowState, initial_state
from app.config import settings
from app.database import session_scope
from app.logging import get_logger
from app.models import ImpactReport
from app.schemas.common import AgentStatus, WorkflowStatus

logger = get_logger("ecr.orchestrator")

APPROVAL_POLL_SECONDS = 0.25


def approval_gate(state: dict[str, Any]) -> dict[str, Any]:
    """Human-in-the-loop checkpoint.

    Blocks the graph until a decision arrives (or the workflow times out), then
    records the decision. A rejection removes the recommendation from the report
    without discarding the analysis.
    """
    workflow_id = state.get("workflow_id", "")
    run = registry.get(workflow_id)
    impact = state.get("impact_analysis") or {}
    selection = state.get("test_selection") or {}

    emit_event(
        workflow_id,
        agent="Workflow",
        agent_key="human_approval",
        status=WorkflowStatus.AWAITING_APPROVAL,
        action="Waiting for a human decision",
        detail=(
            f"{len(impact.get('directly_impacted_components') or [])} directly impacted component(s) "
            f"and {len(selection.get('selected_tests') or [])} recommended tests."
        ),
        ecr_id=state.get("ecr_id", ""),
        payload={
            "direct_components": len(impact.get("directly_impacted_components") or []),
            "selected_tests": len(selection.get("selected_tests") or []),
        },
    )
    if run is None:  # pragma: no cover - defensive
        return {"approval": {"required": True, "status": "AUTO_APPROVED"}}

    run.request_approval()
    granted = run.wait_for_approval(settings.workflow_timeout_seconds)
    decision = run.approval_decision or {}
    status = "APPROVED" if decision.get("approved") else ("REJECTED" if granted else "TIMED_OUT")
    run.status = WorkflowStatus.RUNNING if status != "REJECTED" else WorkflowStatus.RUNNING

    excluded = set(decision.get("excluded_test_ids") or [])
    updates: dict[str, Any] = {
        "approval": {
            "required": True,
            "status": status,
            "decided_by": decision.get("decided_by", ""),
            "comment": decision.get("comment", ""),
            "excluded_test_ids": sorted(excluded),
        }
    }
    if excluded:
        kept = [t for t in (state.get("selected_tests") or []) if t["test_case_id"] not in excluded]
        updates["selected_tests"] = kept
        updates["prioritized_tests"] = [
            t for t in (state.get("prioritized_tests") or []) if t["test_case_id"] not in excluded
        ]
        updates["test_selection"] = {
            **selection,
            "selected_tests": kept,
            "excluded_count": selection.get("excluded_count", 0) + len(excluded),
        }

    emit_event(
        workflow_id,
        agent="Workflow",
        agent_key="human_approval",
        status=AgentStatus.COMPLETED,
        action="Human decision recorded",
        detail=f"{status} by {decision.get('decided_by', 'timeout')}",
        ecr_id=state.get("ecr_id", ""),
        payload=updates["approval"],
    )
    return updates


def needs_approval(state: dict[str, Any]) -> str:
    """Conditional edge: enter the checkpoint only when the user asked for approval."""
    options = state.get("options") or {}
    return "human_approval" if options.get("human_in_the_loop") else "summarization_agent"


def build_graph() -> StateGraph:
    graph = StateGraph(ECRWorkflowState)
    graph.add_node("retrieval_agent", retrieval_agent)
    graph.add_node("correlation_agent", correlation_agent)
    graph.add_node("human_approval", approval_gate)
    graph.add_node("summarization_agent", summarization_agent)

    graph.add_edge(START, "retrieval_agent")
    graph.add_edge("retrieval_agent", "correlation_agent")
    graph.add_conditional_edges(
        "correlation_agent",
        needs_approval,
        {"human_approval": "human_approval", "summarization_agent": "summarization_agent"},
    )
    graph.add_edge("human_approval", "summarization_agent")
    graph.add_edge("summarization_agent", END)
    return graph


@lru_cache
def get_compiled_graph():
    compiled = build_graph().compile()
    logger.info("orchestrator.compiled", nodes=4)
    return compiled


def graph_topology() -> dict[str, Any]:
    """Static topology for the workflow visualisation."""
    from app.agents.state import AGENT_CATALOG, AGENT_STEPS

    return {
        "nodes": [
            {
                "key": descriptor.key,
                "name": descriptor.name,
                "purpose": descriptor.purpose,
                "optional": descriptor.optional,
                "tools": descriptor.tools,
                "steps": AGENT_STEPS.get(descriptor.key, []),
            }
            for descriptor in AGENT_CATALOG
        ],
        "checkpoints": [
            {
                "key": "human_approval",
                "name": "Human approval checkpoint",
                "purpose": "Pauses the analysis until a person approves or rejects it. "
                "It is a gate in the graph, not an agent - it makes no decision itself.",
            }
        ],
        "edges": [
            {"source": "START", "target": "retrieval_agent"},
            {"source": "retrieval_agent", "target": "correlation_agent"},
            {"source": "correlation_agent", "target": "human_approval", "condition": "approval requested"},
            {"source": "correlation_agent", "target": "summarization_agent", "condition": "otherwise"},
            {"source": "human_approval", "target": "summarization_agent"},
            {"source": "summarization_agent", "target": "END"},
        ],
    }


def run_workflow(
    ecr_input: dict[str, Any],
    options: dict[str, Any] | None = None,
    *,
    existing_run=None,
):
    """Execute the graph synchronously and persist the result.

    ``existing_run`` lets the caller register the run (and hand its id to a
    client that wants to subscribe to events) before execution starts.
    """
    options = options or {}
    run = existing_run or registry.create(ecr_input.get("ecr_id", ""), options)
    started = time.perf_counter()
    run.status = WorkflowStatus.RUNNING
    emit_event(
        run.workflow_id,
        agent="Workflow",
        agent_key="workflow",
        status=WorkflowStatus.RUNNING,
        action="Workflow started",
        ecr_id=run.ecr_id,
        detail=f"Analysing {run.ecr_id}",
    )
    state = initial_state(run.workflow_id, ecr_input, options)
    try:
        final_state = get_compiled_graph().invoke(
            state, config={"recursion_limit": 25, "configurable": {"thread_id": run.workflow_id}}
        )
    except Exception as exc:
        run.status = WorkflowStatus.FAILED
        run.finished_at = _now()
        run.errors.append({"agent": "workflow", "error": str(exc), "critical": True})
        emit_event(
            run.workflow_id,
            agent="Workflow",
            agent_key="workflow",
            status=WorkflowStatus.FAILED,
            action="Workflow failed",
            detail=str(exc),
            ecr_id=run.ecr_id,
        )
        logger.exception("workflow.failed", workflow_id=run.workflow_id)
        raise

    duration = round(time.perf_counter() - started, 2)
    run.state = dict(final_state)
    run.report = final_state.get("final_report")
    run.plan = [key for key in (final_state.get("plan") or []) if key != "planning"]
    run.skipped = list(final_state.get("skipped_steps") or [])
    run.errors = list(final_state.get("errors") or [])
    approval = final_state.get("approval") or {}
    run.approval_required = bool(approval.get("required"))
    run.approval_status = approval.get("status", run.approval_status)
    run.confidence = float(
        ((final_state.get("final_report") or {}).get("confidence") or {}).get("overall", 0.0)
    )
    run.status = (
        WorkflowStatus.REJECTED if approval.get("status") == "REJECTED" else WorkflowStatus.COMPLETED
    )
    run.finished_at = _now()

    _persist_report(run.workflow_id, final_state, duration)
    emit_event(
        run.workflow_id,
        agent="Workflow",
        agent_key="workflow",
        status=WorkflowStatus.COMPLETED,
        action="Workflow completed",
        duration=duration,
        confidence=run.confidence,
        ecr_id=run.ecr_id,
        detail=(final_state.get("final_answer") or "")[:400],
    )
    logger.info(
        "workflow.completed",
        workflow_id=run.workflow_id,
        ecr_id=run.ecr_id,
        duration=duration,
    )
    return run, final_state


def _persist_report(workflow_id: str, state: dict[str, Any], duration: float) -> None:
    report = state.get("final_report") or {}
    selection = state.get("test_selection") or {}
    try:
        with session_scope() as db:
            db.add(
                ImpactReport(
                    workflow_id=workflow_id,
                    ecr_id=state.get("ecr_id", ""),
                    confidence=float((report.get("confidence") or {}).get("overall", 0.0)),
                    total_tests=int(selection.get("total_available", 0) or 0),
                    selected_tests=len(selection.get("selected_tests") or []),
                    reduction_percentage=float(selection.get("reduction_percentage", 0.0) or 0.0),
                    execution_time=duration,
                    approval_status=(state.get("approval") or {}).get("status", "NOT_REQUIRED"),
                    report_json=report,
                )
            )
    except Exception as exc:  # pragma: no cover
        logger.warning("report.persist_failed", workflow_id=workflow_id, error=str(exc))


def _now():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)
