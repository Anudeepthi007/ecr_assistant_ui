"""Tools of the Dependency Analysis Agent."""
from __future__ import annotations

from typing import Any, Iterable

from sqlalchemy.orm import Session

from app.agents.tools.registry import tool
from app.graph.dependency_graph import (
    DependencyGraphService,
    build_dependency_graph,
)


@tool("build_graph", "Load the component dependency graph from the database (NetworkX).")
def build_graph(db: Session) -> DependencyGraphService:
    return build_dependency_graph(db)


@tool("downstream_walk", "Find components that depend on the changed ones (blast radius).")
def downstream_walk(
    graph: DependencyGraphService, components: Iterable[str], depth: int = 3
) -> dict[str, int]:
    return graph.downstream(components, max_depth=depth)


@tool("upstream_walk", "Find components the changed ones rely on.")
def upstream_walk(
    graph: DependencyGraphService, components: Iterable[str], depth: int = 2
) -> dict[str, int]:
    return graph.upstream(components, max_depth=depth)


@tool("critical_paths", "Highest-propagation paths from an entry point into the changed component.")
def critical_paths(
    graph: DependencyGraphService, components: Iterable[str], max_paths: int = 5
) -> list[list[str]]:
    return graph.critical_paths(components, max_paths=max_paths)


@tool("dependency_subgraph", "Nodes and edges around the change for the UI graph view.")
def dependency_subgraph(
    graph: DependencyGraphService, components: Iterable[str], depth: int = 2
) -> dict[str, Any]:
    return graph.subgraph_payload(components, max_depth=depth)
