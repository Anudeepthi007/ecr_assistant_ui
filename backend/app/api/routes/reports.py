"""Report retrieval and rendering, plus dashboard analytics and feedback."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse, PlainTextResponse

from app.dependencies import DbSession
from app.models import Component, Dependency, Feedback, TestCase
from app.repositories import (
    ComponentRepository,
    ECRRepository,
    FeedbackRepository,
    ImpactReportRepository,
)
from app.schemas.report import ECRIntelligenceReport
from app.services import ecr_service
from app.services.report_service import render_html, render_markdown

router = APIRouter(tags=["reports"])


@router.get("/ecr/{ecr_id}/report")
def get_report(
    ecr_id: str,
    db: DbSession,
    format: str = Query("json", pattern="^(json|markdown|html)$"),
):
    report = ecr_service.latest_report(db, ecr_id)
    if not report:
        raise HTTPException(status_code=404, detail=f"no report available for {ecr_id}")
    if format == "json":
        return report
    model = ECRIntelligenceReport.model_validate(report)
    if format == "markdown":
        return PlainTextResponse(render_markdown(model), media_type="text/markdown")
    return HTMLResponse(render_html(model))


@router.get("/reports")
def list_reports(db: DbSession, limit: int = Query(50, le=200)) -> list[dict[str, Any]]:
    return [report.summary() for report in ImpactReportRepository(db).all_reports(limit)]


@router.get("/dashboard/stats")
def dashboard_stats(db: DbSession) -> dict[str, Any]:
    """Aggregates for the dashboard landing page."""
    reports = ImpactReportRepository(db).all_reports(200)
    ecrs = ECRRepository(db)
    latest_by_ecr: dict[str, Any] = {}
    for report in reports:
        latest_by_ecr.setdefault(report.ecr_id, report)

    analysed = list(latest_by_ecr.values())
    average_reduction = (
        round(sum(r.reduction_percentage for r in analysed) / len(analysed), 1) if analysed else 0.0
    )
    average_time = (
        round(sum(r.execution_time for r in analysed) / len(analysed), 1) if analysed else 0.0
    )
    tests_saved = sum(max(0, r.total_tests - r.selected_tests) for r in analysed)

    return {
        "total_ecrs": ecrs.count(),
        "analysed_ecrs": len(analysed),
        "average_regression_reduction": average_reduction,
        "average_analysis_seconds": average_time,
        "tests_avoided": tests_saved,
        "catalogue": {
            "components": db.query(Component).count(),
            "dependencies": db.query(Dependency).count(),
            "test_cases": db.query(TestCase).count(),
        },
        "recent_ecrs": [row.as_dict() for row in ecrs.recent(8)],
        "recent_analyses": [report.summary() for report in reports[:8]],
    }


@router.get("/components")
def list_components(db: DbSession) -> list[dict[str, Any]]:
    return [row.as_dict() for row in ComponentRepository(db).list()]


@router.get("/components/graph")
def component_graph(db: DbSession) -> dict[str, Any]:
    """The full landscape graph (used by the dependency visualisation)."""
    from app.graph.dependency_graph import build_dependency_graph

    graph = build_dependency_graph(db)
    return {
        "nodes": [
            {**graph.node(node_id), "component_id": node_id} for node_id in graph.graph.nodes
        ],
        "edges": [
            {"source": source, "target": target, **data}
            for source, target, data in graph.graph.edges(data=True)
        ],
        "stats": graph.stats(),
    }


@router.post("/feedback")
def submit_feedback(payload: dict[str, Any], db: DbSession) -> dict[str, Any]:
    """Record whether a recommendation was useful (feedback loop)."""
    feedback = Feedback(
        ecr_id=ecr_service.normalise_ecr_id(payload.get("ecr_id", "")),
        workflow_id=payload.get("workflow_id", ""),
        target_type=payload.get("target_type", "RECOMMENDATION"),
        target_id=payload.get("target_id", ""),
        useful=bool(payload.get("useful", True)),
        comment=payload.get("comment", ""),
    )
    FeedbackRepository(db).add(feedback)
    return feedback.as_dict()


@router.get("/feedback")
def list_feedback(db: DbSession) -> list[dict[str, Any]]:
    return [row.as_dict() for row in FeedbackRepository(db).list()]
