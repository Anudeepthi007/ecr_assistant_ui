"""Retrieval Agent step: code impact analysis.

Direct impact = the files declared on the change. Indirect impact = modules that
import them, walked over the AST-derived import graph. When an ECR declares no
files (a description-only request), the agent falls back to keyword discovery
over the parsed symbol table.
"""
from __future__ import annotations

from typing import Any

from app.agents.tools.code_tools import analyze_changed_files, repository_stats
from app.llm.provider import get_llm
from app.schemas.impact import CodeImpactAnalysis, CodeSymbol


def code_impact_step(state: dict[str, Any]) -> dict[str, Any]:
    ecr = state["ecr_input"]
    analysis = state.get("ecr_analysis") or {}
    changed_files = list(ecr.get("changed_files") or [])
    keywords = analysis.get("technical_keywords") or []

    facts = analyze_changed_files(changed_files, keywords=keywords)
    stats = repository_stats()

    symbols = [
        CodeSymbol(
            file=item["file"],
            symbol=item["symbol"],
            kind=item["kind"],
            component=item["component"],
            calls=item["calls"][:6],
        )
        for item in facts["symbols"][:40]
    ]

    declared_only = not facts["resolved_modules"] and bool(changed_files)
    confidence = round(
        min(
            0.96,
            0.35
            + 0.35 * bool(facts["resolved_modules"])
            + 0.15 * bool(facts["dependent_modules"])
            + 0.1 * bool(changed_files),
        ),
        3,
    )
    if declared_only:
        confidence = min(confidence, 0.55)

    baseline = (
        f"Parsed {stats['modules']} modules ({stats['import_edges']} import edges) and resolved "
        f"{len(facts['resolved_modules'])} changed module(s). "
        f"Direct impact: {', '.join(facts['direct_components']) or 'none resolved'}. "
        f"{len(facts['dependent_modules'])} module(s) import the changed code, giving indirect "
        f"impact on {', '.join(facts['indirect_components']) or 'no further components'}."
    )
    if declared_only:
        baseline += (
            " The declared files are not present in the analysed repository, so components were "
            "resolved by path convention only."
        )

    reasoning = get_llm().narrate(
        task="Explain the code level impact of this change",
        context={
            "changed_files": changed_files,
            "resolved_modules": facts["resolved_modules"],
            "dependent_modules": list(facts["dependent_modules"]),
            "direct_components": facts["direct_components"],
            "indirect_components": facts["indirect_components"],
            "apis": facts["apis"],
        },
        fallback=baseline,
    )

    result = CodeImpactAnalysis(
        directly_impacted_files=facts["direct_files"],
        impacted_symbols=symbols,
        impacted_services=facts["direct_components"],
        potentially_impacted_services=facts["indirect_components"],
        impacted_apis=facts["apis"],
        database_entities=facts["database_entities"],
        change_surface=facts["change_surface"],
        language_analyzers=facts["analyzers"],
        confidence=confidence,
        reasoning=reasoning,
    )
    return {
        "code_impact": {
            **result.model_dump(mode="json"),
            "dependent_files": facts["dependent_files"],
            "unresolved_files": facts["unresolved_files"],
            "repository": facts["repository"],
            "modules_indexed": facts["modules_indexed"],
        },
        "tools_used": {
            "code_impact": ["analyze_changed_files", "walk_import_graph", "repository_stats"]
        },
        "_confidence": confidence,
        "_reasoning": reasoning,
        "_summary": {
            "direct_files": facts["direct_files"][:8],
            "direct_components": facts["direct_components"],
            "indirect_components": facts["indirect_components"],
            "apis": facts["apis"][:6],
        },
    }
