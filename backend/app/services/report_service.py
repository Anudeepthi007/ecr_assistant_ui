"""Report assembly and rendering (JSON / Markdown / HTML)."""
from __future__ import annotations

import html
from datetime import datetime, timezone
from typing import Any

from app.schemas.common import ConfidenceBand
from app.schemas.report import (
    ConfidenceReport,
    ECRIntelligenceReport,
    ReportSection,
)
from app.services.confidence import compute_confidence

SECTION_ORDER = [
    ("executive_summary", "Executive Summary"),
    ("ecr_overview", "Steps to Reproduce"),
    ("change_classification", "Change Classification"),
    ("affected_requirements", "Affected Requirements"),
    ("historical_defects", "Defect Analysis"),
    ("team_signals", "Review Comments and Evidence"),
    ("correlation_findings", "Correlation Findings"),
    ("code_impact", "Code Impact"),
    ("dependency_impact", "Dependency Impact"),
    ("impacted_components", "Impacted Components"),
    ("recommended_tests", "Recommended Regression Tests"),
    ("test_prioritization", "Test Prioritization"),
    ("mitigations", "Recommended Actions"),
    ("confidence", "Confidence Score"),
    ("execution_trace", "Agent Execution Trace"),
]


def build_report(state: dict[str, Any]) -> ECRIntelligenceReport:
    """Assemble the final report object from the workflow state."""
    ecr = state.get("ecr_input") or {}
    impact = state.get("impact_analysis") or {}
    selection = state.get("test_selection") or {}
    prioritization = state.get("test_prioritization") or {}
    collaboration = state.get("collaboration_analysis") or {}
    correlation = state.get("correlation") or {}
    errors = state.get("errors") or []

    overall, penalties = compute_confidence(state.get("step_confidence") or {}, errors=errors)
    confidence = ConfidenceReport(
        overall=overall,
        band=ConfidenceBand.from_score(overall),
        per_step=state.get("step_confidence") or {},
        penalties=penalties,
    )

    report = ECRIntelligenceReport(
        workflow_id=state.get("workflow_id", ""),
        ecr_id=state.get("ecr_id", ""),
        generated_at=datetime.now(timezone.utc),
        title=ecr.get("title", ""),
        executive_summary=state.get("final_answer") or impact.get("executive_summary", ""),
        ecr_overview={
            "ecr_id": state.get("ecr_id", ""),
            "title": ecr.get("title", ""),
            "description": ecr.get("description", ""),
            "business_domain": ecr.get("business_domain", ""),
            "priority": ecr.get("priority", ""),
            "requested_by": ecr.get("requested_by", ""),
            "target_release": ecr.get("target_release", ""),
            "changed_files": ecr.get("changed_files", []),
            "steps_to_reproduce": ecr.get("steps_to_reproduce", ""),
            "observed_behavior": ecr.get("observed_behavior", ""),
            "expected_behavior": ecr.get("expected_behavior", ""),
        },
        change_classification=state.get("ecr_analysis"),
        retrieval_plan=state.get("retrieval_plan") or {},
        correlation_review=state.get("correlation_review") or {},
        requirement_analysis=state.get("requirement_analysis"),
        defect_analysis=state.get("defect_analysis"),
        defect_insights=state.get("defect_insights") or {},
        defect_summary=state.get("defect_summary") or "",
        code_impact=_strip_extras(state.get("code_impact")),
        dependency_analysis=_strip_extras(state.get("dependency_analysis")),
        impact_assessment=impact or None,
        test_selection=selection or None,
        test_prioritization=prioritization or None,
        mitigations=impact.get("mitigations", []),
        confidence=confidence,
        execution_trace=state.get("execution_trace") or [],
        errors=errors,
        approval=state.get("approval") or {},
        metrics={
            "total_tests": selection.get("total_available", 0),
            "candidate_tests": selection.get("total_candidates", 0),
            "selected_tests": len(selection.get("selected_tests") or []),
            "reduction_percentage": selection.get("reduction_percentage", 0.0),
            # Execution-time estimates are intentionally not published on the report:
            # no record states how long a suite takes to run.
            "priority_distribution": selection.get("priority_distribution", {}),
            "correlated_artifacts": len((correlation.get("graph") or {}).get("nodes") or []),
            "correlated_links": len((correlation.get("graph") or {}).get("edges") or []),
            "comments": collaboration.get("comment_count", 0),
            "evidence": collaboration.get("evidence_count", 0),
        },
    )
    report.sections = _build_sections(report, state)
    return report


def _strip_extras(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """Drop the internal-only keys that are not part of the published schema."""
    if not payload:
        return None
    drop = {"propagation", "distances", "graph_stats", "dependent_files", "unresolved_files",
            "repository", "modules_indexed"}
    return {k: v for k, v in payload.items() if k not in drop}


def _build_sections(report: ECRIntelligenceReport, state: dict[str, Any]) -> list[ReportSection]:
    impact = state.get("impact_analysis") or {}
    selection = state.get("test_selection") or {}
    prioritization = state.get("test_prioritization") or {}
    collaboration = state.get("collaboration_analysis") or {}
    requirement_analysis = state.get("requirement_analysis") or {}
    defect_analysis = state.get("defect_analysis") or {}
    dependency = state.get("dependency_analysis") or {}
    code_impact = state.get("code_impact") or {}
    classification = state.get("ecr_analysis") or {}

    sections: list[ReportSection] = []
    for key, title in SECTION_ORDER:
        body = ""
        data: dict[str, Any] = {}
        if key == "executive_summary":
            body = report.executive_summary
        elif key == "ecr_overview":
            # Show only the dedicated field. Falling back to the description made
            # the section claim steps the record never supplied.
            body = (
                (report.ecr_overview.get("steps_to_reproduce") or "").strip()
                or "No steps to reproduce provided for this ECR."
            )
            data = report.ecr_overview
        elif key == "change_classification":
            body = classification.get("summary", "")
            data = {**classification, "retrieval_plan": state.get("retrieval_plan") or {}}
        elif key == "affected_requirements":
            body = requirement_analysis.get("reasoning", "")
            data = {"requirements": requirement_analysis.get("matched_requirements", [])}
        elif key == "historical_defects":
            insights = state.get("defect_insights") or {}
            body = state.get("defect_summary") or defect_analysis.get("reasoning", "")
            data = {
                "defects": insights.get("defects") or defect_analysis.get("similar_defects", []),
                "not_covered": insights.get("not_covered", []),
                "common_causes": insights.get("common_causes", []),
            }
        elif key == "team_signals":
            body = collaboration.get("reasoning", "")
            data = {
                "decisions": (collaboration.get("signals") or {}).get("decisions", []),
                "risks": (collaboration.get("signals") or {}).get("risks", []),
                "open_concerns": collaboration.get("open_concerns", []),
                "evidence_gaps": collaboration.get("evidence_gaps", []),
            }
        elif key == "correlation_findings":
            review = state.get("correlation_review") or {}
            lines = [
                f"- {label}: {item['text']}"
                for label, bucket in (("Contradiction", "conflicts"), ("Gap", "gaps"), ("Key link", "key_links"))
                for item in review.get(bucket) or []
            ]
            body = "\n".join([review.get("summary", ""), *lines]).strip()
            data = review
        elif key == "code_impact":
            body = code_impact.get("reasoning", "")
            data = {
                "files": code_impact.get("directly_impacted_files", []),
                "apis": code_impact.get("impacted_apis", []),
                "symbols": code_impact.get("impacted_symbols", [])[:15],
            }
        elif key == "dependency_impact":
            body = dependency.get("reasoning", "Dependency analysis was not required for this change.")
            data = {
                "direct": dependency.get("direct_dependencies", []),
                "indirect": dependency.get("indirect_dependencies", []),
                "critical_paths": dependency.get("critical_dependency_paths", []),
            }
        elif key == "impacted_components":
            body = impact.get("technical_impact", "")
            data = {
                "direct": impact.get("directly_impacted_components", []),
                "indirect": impact.get("indirectly_impacted_components", []),
            }
        elif key == "recommended_tests":
            body = selection.get("reasoning", "")
            data = {
                "selected": selection.get("selected_tests", []),
                "metrics": report.metrics,
            }
        elif key == "test_prioritization":
            body = prioritization.get("reasoning", "")
            data = {
                "waves": prioritization.get("waves", {}),
                "strategy": prioritization.get("strategy", ""),
            }
        elif key == "mitigations":
            body = "\n".join(f"- {item}" for item in report.mitigations)
            data = {"mitigations": report.mitigations}
        elif key == "confidence":
            body = (
                f"Overall confidence {report.confidence.overall:.0%} "
                f"({report.confidence.band.value})."
            )
            data = report.confidence.model_dump(mode="json")
        elif key == "execution_trace":
            body = f"{len(report.execution_trace)} step(s) executed."
            data = {"trace": report.execution_trace}
        sections.append(ReportSection(key=key, title=title, body=body, data=data))
    return sections


# --------------------------------------------------------------------------
# Renderers
# --------------------------------------------------------------------------
def render_markdown(report: ECRIntelligenceReport) -> str:
    lines: list[str] = [
        f"# ECR Intelligence Report - {report.ecr_id}",
        "",
        f"**{report.title}**",
        "",
        f"- Generated: {report.generated_at.isoformat()}",
        f"- Workflow: `{report.workflow_id}`",
        f"- Confidence: **{report.confidence.overall:.0%} ({report.confidence.band.value})**",
        "",
    ]
    metrics = report.metrics
    if metrics.get("total_tests"):
        lines += [
            "## Regression Optimisation",
            "",
            f"| Metric | Value |",
            f"| --- | --- |",
            f"| Full regression suite | {metrics.get('total_tests', 0)} tests |",
            f"| Candidates discovered | {metrics.get('candidate_tests', 0)} tests |",
            f"| AI recommended | {metrics.get('selected_tests', 0)} tests |",
            f"| Reduction | {metrics.get('reduction_percentage', 0)}% |",
            "",
        ]
    for section in report.sections:
        if section.key in ("executive_summary",):
            lines += [f"## {section.title}", "", section.body or "_Not available._", ""]
            continue
        lines += [f"## {section.title}", "", section.body or "_Not available._", ""]
        if section.key == "affected_requirements":
            for requirement in section.data.get("requirements", []):
                lines.append(
                    f"- **{requirement['requirement_id']}** {requirement['title']} - "
                    f"{requirement['relevance']:.0f}% ({requirement['match_type']}): {requirement['reason']}"
                )
            lines.append("")
        if section.key == "historical_defects":
            for defect in section.data.get("defects", []):
                if defect.get("chance_of_recurrence"):
                    lines.append(
                        f"- **{defect['defect_id']}** [{defect['severity']}] {defect['title']}. "
                        f"Can it happen again: {defect['chance_of_recurrence']}. "
                        f"{defect['why_it_matters']} {defect['what_to_check']}"
                    )
                else:  # reports saved before defect analysis existed
                    lines.append(
                        f"- **{defect['defect_id']}** [{defect['severity']}] {defect['title']} - "
                        f"{defect.get('similarity', 0):.0f}% similar. {defect.get('reason', '')}"
                    )
            lines.append("")
        if section.key == "recommended_tests":
            lines += ["| Test | Priority | Relevance | Component | Reason |", "| --- | --- | --- | --- | --- |"]
            for test in section.data.get("selected", [])[:60]:
                lines.append(
                    f"| {test['test_case_id']} | {test['priority']} | {test['relevance_score']:.0f}% | "
                    f"{test['component']} | {test['reason']} |"
                )
            lines.append("")
    return "\n".join(lines)


def render_html(report: ECRIntelligenceReport) -> str:
    def esc(value: Any) -> str:
        return html.escape(str(value))

    rows = "".join(
        f"<tr><td>{esc(t['test_case_id'])}</td><td><span class='pill {esc(t['priority'])}'>"
        f"{esc(t['priority'])}</span></td><td>{esc(round(t['relevance_score']))}%</td>"
        f"<td>{esc(t['component'])}</td><td>{esc(t['reason'])}</td></tr>"
        for section in report.sections
        if section.key == "recommended_tests"
        for t in section.data.get("selected", [])[:80]
    )
    sections_html = "".join(
        f"<section><h2>{esc(s.title)}</h2><p>{esc(s.body).replace(chr(10), '<br/>')}</p></section>"
        for s in report.sections
        if s.key not in ("recommended_tests", "execution_trace")
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"/>
<title>ECR Intelligence Report - {esc(report.ecr_id)}</title>
<style>
 body {{ font-family: 'Segoe UI', system-ui, sans-serif; background:#0b1020; color:#e6ebff; margin:0; padding:40px; }}
 h1 {{ margin:0 0 4px; font-size:28px; }}
 h2 {{ font-size:16px; text-transform:uppercase; letter-spacing:.08em; color:#8ea2ff; margin:32px 0 8px; }}
 .meta {{ color:#9aa7c7; margin-bottom:24px; }}
 .score {{ display:inline-block; padding:12px 20px; border-radius:12px; background:#161d38; margin-right:12px; }}
 .score b {{ font-size:28px; }}
 table {{ width:100%; border-collapse:collapse; margin-top:12px; font-size:13px; }}
 th, td {{ text-align:left; padding:8px 10px; border-bottom:1px solid #223; vertical-align:top; }}
 th {{ color:#8ea2ff; text-transform:uppercase; font-size:11px; letter-spacing:.06em; }}
 .pill {{ padding:2px 8px; border-radius:999px; font-size:11px; font-weight:600; }}
 .P0 {{ background:#5b1a2a; color:#ffb3c2; }} .P1 {{ background:#5a3c12; color:#ffd79a; }}
 .P2 {{ background:#14385a; color:#a8d5ff; }} .P3 {{ background:#233; color:#9aa7c7; }}
 section p {{ line-height:1.6; color:#c9d3ee; }}
</style></head><body>
<h1>ECR Intelligence Report</h1>
<div class="meta">{esc(report.ecr_id)} &middot; {esc(report.title)} &middot; generated {esc(report.generated_at.isoformat())}</div>
<div class="score">Confidence<br/><b>{esc(round(report.confidence.overall * 100))}%</b> {esc(report.confidence.band.value)}</div>
<div class="score">Regression<br/><b>{esc(report.metrics.get('selected_tests', 0))}</b> of {esc(report.metrics.get('total_tests', 0))} tests
 ({esc(report.metrics.get('reduction_percentage', 0))}% reduction)</div>
{sections_html}
<section><h2>Recommended Regression Tests</h2>
<table><thead><tr><th>Test</th><th>Priority</th><th>Relevance</th><th>Component</th><th>Why selected</th></tr></thead>
<tbody>{rows}</tbody></table></section>
</body></html>"""
