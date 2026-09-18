"""Analysis endpoints: run the agents, stream progress, read the results."""
from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from app.agents.runtime import registry
from app.config import settings
from app.dependencies import DbSession
from app.schemas.agent import ApprovalDecision
from app.schemas.ecr import AnalyzeRequest
from app.services import ecr_service

router = APIRouter(prefix="/ecr", tags=["analysis"])


def _run_or_404(ecr_id: str):
    run = registry.latest_for_ecr(ecr_service.normalise_ecr_id(ecr_id))
    if run is None:
        raise HTTPException(status_code=404, detail=f"no analysis run found for {ecr_id}")
    return run


@router.post("/{ecr_id}/analyze", status_code=status.HTTP_202_ACCEPTED)
def analyze(
    ecr_id: str,
    db: DbSession,
    payload: AnalyzeRequest | None = None,
    wait: bool = Query(False, description="Block until the workflow finishes"),
) -> dict[str, Any]:
    """Trigger the agentic analysis for an ECR number."""
    request = payload or AnalyzeRequest()
    options: dict[str, Any] = {
        "human_in_the_loop": (
            settings.human_in_the_loop
            if request.human_in_the_loop is None
            else request.human_in_the_loop
        ),
        "force_full_analysis": request.force_full_analysis,
        "demo_mode": request.demo_mode,
    }
    if request.description_override:
        options["description_override"] = request.description_override
    try:
        run = ecr_service.start_analysis(db, ecr_id, options, background=not wait)
    except ecr_service.ECRNotFound as exc:
        raise HTTPException(status_code=404, detail=f"{ecr_id} not found") from exc
    return {
        "workflow_id": run.workflow_id,
        "ecr_id": run.ecr_id,
        "status": run.status,
        "stream_url": f"{settings.api_prefix}/workflows/{run.workflow_id}/stream",
    }


@router.get("/{ecr_id}/analysis")
def get_analysis(ecr_id: str, db: DbSession) -> dict[str, Any]:
    """Full analysis payload (live run if available, else the last persisted)."""
    run = registry.latest_for_ecr(ecr_service.normalise_ecr_id(ecr_id))
    if run and run.state:
        state = run.state
        return {
            "workflow_id": run.workflow_id,
            "ecr_id": run.ecr_id,
            "status": run.status,
            "duration": run.duration,
            "answer": state.get("final_answer"),
            "citations": state.get("answer_citations", []),
            "question": state.get("question"),
            "ecr_analysis": state.get("ecr_analysis"),
            "retrieval_plan": state.get("retrieval_plan"),
            "correlation_review": state.get("correlation_review"),
            "requirement_analysis": state.get("requirement_analysis"),
            "defect_analysis": state.get("defect_analysis"),
            "defect_insights": state.get("defect_insights"),
            "defect_summary": state.get("defect_summary"),
            "code_impact": state.get("code_impact"),
            "dependency_analysis": state.get("dependency_analysis"),
            "collaboration_analysis": state.get("collaboration_analysis"),
            "correlation": state.get("correlation"),
            "impact_analysis": state.get("impact_analysis"),
            "test_discovery": {
                k: v for k, v in (state.get("test_discovery") or {}).items()
                if k != "candidate_tests"
            },
            "test_selection": state.get("test_selection"),
            "test_prioritization": state.get("test_prioritization"),
            "comments": state.get("comments", []),
            "evidence": state.get("evidence", []),
            "approval": state.get("approval", {}),
            "plan": state.get("plan", []),
            "plan_detail": state.get("plan_detail", {}),
            "skipped_steps": state.get("skipped_steps", []),
            "execution_trace": state.get("execution_trace", []),
            "errors": state.get("errors", []),
            "report": state.get("final_report"),
        }
    report = ecr_service.latest_report(db, ecr_id)
    if not report:
        raise HTTPException(status_code=404, detail=f"no analysis available for {ecr_id}")
    from app.models import Comment, Evidence

    resolved = ecr_service.normalise_ecr_id(ecr_id)
    return {
        **page_fields_from_report(report),
        "ecr_id": resolved,
        "status": "COMPLETED",
        "comments": [c.as_dict() for c in db.query(Comment).filter(Comment.ecr_id == resolved)],
        "evidence": [e.as_dict() for e in db.query(Evidence).filter(Evidence.ecr_id == resolved)],
        "report": report,
    }


def page_fields_from_report(report: dict[str, Any]) -> dict[str, Any]:
    """Rebuild the analysis page fields from a saved report.

    Live runs are held in memory, so after a backend restart only the saved report
    is left. Without this the page would show an ECR as analysed but empty.
    """
    return {
        "workflow_id": report.get("workflow_id"),
        "duration": None,
        "answer": report.get("executive_summary"),
        "citations": [],
        "ecr_analysis": report.get("change_classification"),
        "retrieval_plan": report.get("retrieval_plan") or None,
        "correlation_review": report.get("correlation_review") or None,
        "requirement_analysis": report.get("requirement_analysis"),
        "defect_analysis": report.get("defect_analysis"),
        "defect_insights": report.get("defect_insights") or None,
        "defect_summary": report.get("defect_summary") or "",
        "code_impact": report.get("code_impact"),
        "dependency_analysis": report.get("dependency_analysis"),
        "impact_analysis": report.get("impact_assessment"),
        "test_selection": report.get("test_selection"),
        "test_prioritization": report.get("test_prioritization"),
        "approval": report.get("approval") or {},
        "plan_detail": {},
        "skipped_steps": [],
        "execution_trace": report.get("execution_trace") or [],
        "errors": report.get("errors") or [],
    }


@router.get("/{ecr_id}/impact")
def get_impact(ecr_id: str, db: DbSession) -> dict[str, Any]:
    state = ecr_service.latest_state(ecr_id) or {}
    if state.get("impact_analysis"):
        return {
            "impact": state["impact_analysis"],
            "dependency": state.get("dependency_analysis"),
            "code_impact": state.get("code_impact"),
            "defects": state.get("defect_analysis"),
        }
    report = ecr_service.latest_report(db, ecr_id)
    if not report:
        raise HTTPException(status_code=404, detail=f"no impact analysis available for {ecr_id}")
    return {
        "impact": report.get("impact_assessment"),
        "dependency": report.get("dependency_analysis"),
        "code_impact": report.get("code_impact"),
        "defects": report.get("defect_analysis"),
    }


@router.get("/{ecr_id}/tests")
def get_tests(
    ecr_id: str,
    db: DbSession,
    priority: str | None = Query(None, description="Filter by P0/P1/P2/P3"),
) -> dict[str, Any]:
    state = ecr_service.latest_state(ecr_id) or {}
    selection = state.get("test_selection")
    prioritization = state.get("test_prioritization")
    if not selection:
        report = ecr_service.latest_report(db, ecr_id)
        if not report:
            raise HTTPException(status_code=404, detail=f"no test selection available for {ecr_id}")
        selection = report.get("test_selection") or {}
        prioritization = report.get("test_prioritization") or {}
    tests = (prioritization or {}).get("prioritized_tests") or selection.get("selected_tests") or []
    if priority:
        wanted = {p.strip().upper() for p in priority.split(",")}
        tests = [test for test in tests if test.get("priority") in wanted]
    return {
        "ecr_id": ecr_service.normalise_ecr_id(ecr_id),
        "total_available": selection.get("total_available", 0),
        "total_candidates": selection.get("total_candidates", 0),
        "selected": len(selection.get("selected_tests") or []),
        "reduction_percentage": selection.get("reduction_percentage", 0.0),
        "estimated_duration_minutes": selection.get("estimated_duration_minutes", 0.0),
        "baseline_duration_minutes": selection.get("baseline_duration_minutes", 0.0),
        "priority_distribution": selection.get("priority_distribution", {}),
        "waves": (prioritization or {}).get("waves", {}),
        "strategy": (prioritization or {}).get("strategy", ""),
        "tests": tests,
    }


@router.get("/{ecr_id}/workflow")
def get_workflow(ecr_id: str) -> dict[str, Any]:
    from app.agents.orchestrator import graph_topology

    run = _run_or_404(ecr_id)
    summary = run.summary()
    summary["events"] = [event.model_dump(mode="json") for event in summary["events"]]
    summary["topology"] = graph_topology()
    summary["tools_used"] = (run.state or {}).get("tools_used", {})
    return summary


@router.post("/{ecr_id}/approve")
def approve(ecr_id: str, decision: ApprovalDecision) -> dict[str, Any]:
    """Resume a workflow paused at the human approval checkpoint."""
    run = _run_or_404(ecr_id)
    if run.approval_status != "PENDING":
        raise HTTPException(
            status_code=409, detail=f"workflow is not awaiting approval ({run.approval_status})"
        )
    run.resolve_approval(decision.model_dump())
    return {"workflow_id": run.workflow_id, "approval_status": run.approval_status}


# ---------------------------------------------------------------------------
# Workflow-scoped endpoints
# ---------------------------------------------------------------------------
workflow_router = APIRouter(prefix="/workflows", tags=["workflow"])


@workflow_router.get("")
def list_workflows() -> list[dict[str, Any]]:
    return [
        {
            "workflow_id": run.workflow_id,
            "ecr_id": run.ecr_id,
            "status": run.status,
            "started_at": run.started_at,
            "duration": run.duration,
            "progress": run.progress,
            "confidence": run.confidence,
        }
        for run in registry.all()
    ]


@workflow_router.get("/{workflow_id}")
def get_workflow_by_id(workflow_id: str) -> dict[str, Any]:
    run = registry.get(workflow_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"workflow {workflow_id} not found")
    summary = run.summary()
    summary["events"] = [event.model_dump(mode="json") for event in summary["events"]]
    return summary


@workflow_router.get("/{workflow_id}/stream")
async def stream_workflow(workflow_id: str) -> StreamingResponse:
    """Server-Sent Events stream of live agent progress."""
    run = registry.get(workflow_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"workflow {workflow_id} not found")

    async def event_source():
        cursor = 0
        idle = 0.0
        yield _sse("connected", {"workflow_id": workflow_id, "ecr_id": run.ecr_id})
        while True:
            cursor, events = run.events_after(cursor)
            for event in events:
                yield _sse("agent", event.model_dump(mode="json"))
                idle = 0.0
            if run.finished_at is not None:
                yield _sse(
                    "done",
                    {
                        "workflow_id": workflow_id,
                        "status": run.status,
                        "duration": run.duration,
                        "confidence": run.confidence,
                        "approval_status": run.approval_status,
                    },
                )
                return
            await asyncio.sleep(0.25)
            idle += 0.25
            if idle >= 10.0:  # keep proxies from closing an idle connection
                yield _sse("ping", {"progress": run.progress, "status": run.status})
                idle = 0.0

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"
