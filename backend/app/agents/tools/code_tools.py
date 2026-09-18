"""Tools of the Code Impact Analysis Agent."""
from __future__ import annotations

from typing import Any, Iterable

from app.agents.tools.registry import tool
from app.services.code_analysis_service import get_code_analysis_service


@tool("analyze_changed_files", "Parse the repository with the Python AST analyzer and map impact.")
def analyze_changed_files(
    changed_files: Iterable[str], *, keywords: Iterable[str] = ()
) -> dict[str, Any]:
    return get_code_analysis_service().analyze_change(changed_files, keywords=keywords)


@tool("resolve_component_owner", "Map a repository path onto the owning component.")
def resolve_component_owner(file_path: str) -> str | None:
    return get_code_analysis_service().component_for_path(file_path)


@tool("walk_import_graph", "Walk the module import graph to find transitive dependents.")
def walk_import_graph(modules: Iterable[str], depth: int = 2) -> dict[str, int]:
    return get_code_analysis_service().dependents(modules, max_depth=depth)


@tool("repository_stats", "Summarise the analysed repository (modules, edges, languages).")
def repository_stats() -> dict[str, Any]:
    return get_code_analysis_service().stats()
