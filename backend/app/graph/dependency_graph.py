"""Component dependency graph (NetworkX).

The graph is directed: an edge ``A -> B`` means "A depends on B".
Therefore, when B changes:
  * successors of B (things B depends on) are *upstream* of the change,
  * predecessors of B (things that depend on B) are *downstream* and carry the
    regression risk.

``DependencyGraphService`` is the only place that knows about NetworkX, which
keeps a future Neo4j implementation a drop-in replacement
(see :class:`BaseDependencyGraph`).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Iterable

import networkx as nx
from sqlalchemy.orm import Session

from app.logging import get_logger
from app.models import Component, Dependency

logger = get_logger("ecr.graph")

CRITICALITY_WEIGHT = {"CRITICAL": 1.0, "HIGH": 0.8, "MEDIUM": 0.5, "LOW": 0.25}
DEPENDENCY_TYPE_WEIGHT = {
    "LIBRARY": 1.0,  # compiled in - change propagates immediately
    "DB_ACCESS": 0.9,
    "SYNC_API": 0.85,
    "ASYNC_EVENT": 0.55,
    "CONFIG": 0.4,
}


class BaseDependencyGraph(ABC):
    """Contract a Neo4j-backed implementation would also satisfy."""

    @abstractmethod
    def load(self, db: Session) -> None: ...

    @abstractmethod
    def downstream(self, components: Iterable[str], max_depth: int = 3) -> dict[str, int]: ...

    @abstractmethod
    def upstream(self, components: Iterable[str], max_depth: int = 3) -> dict[str, int]: ...


class DependencyGraphService(BaseDependencyGraph):
    """In-process NetworkX implementation."""

    def __init__(self) -> None:
        self.graph = nx.DiGraph()

    # -- lifecycle --------------------------------------------------------
    def load(self, db: Session) -> "DependencyGraphService":
        graph = nx.DiGraph()
        for component in db.query(Component).all():
            graph.add_node(component.component_id, **component.as_dict())
        for dependency in db.query(Dependency).all():
            if not dependency.source or not dependency.target:
                continue
            graph.add_edge(
                dependency.source.component_id,
                dependency.target.component_id,
                dependency_type=dependency.dependency_type,
                criticality=dependency.criticality,
                weight=dependency.weight,
                propagation=self.edge_propagation(dependency.dependency_type, dependency.criticality),
                description=dependency.description,
            )
        self.graph = graph
        logger.info("graph.loaded", nodes=graph.number_of_nodes(), edges=graph.number_of_edges())
        return self

    @staticmethod
    def edge_propagation(dependency_type: str, criticality: str) -> float:
        """How strongly a change propagates along this edge (0..1)."""
        return round(
            DEPENDENCY_TYPE_WEIGHT.get(dependency_type, 0.6)
            * (0.6 + 0.4 * CRITICALITY_WEIGHT.get(criticality, 0.5)),
            3,
        )

    # -- traversal --------------------------------------------------------
    def _bfs(self, components: Iterable[str], max_depth: int, reverse: bool) -> dict[str, int]:
        graph = self.graph.reverse(copy=False) if reverse else self.graph
        distances: dict[str, int] = {}
        frontier = [c for c in components if c in graph]
        depth = 0
        seen = set(frontier)
        while frontier and depth < max_depth:
            depth += 1
            next_frontier: list[str] = []
            for node in frontier:
                for neighbour in graph.successors(node):
                    if neighbour in seen:
                        continue
                    seen.add(neighbour)
                    distances[neighbour] = depth
                    next_frontier.append(neighbour)
            frontier = next_frontier
        return distances

    def downstream(self, components: Iterable[str], max_depth: int = 3) -> dict[str, int]:
        """Components that depend on the changed ones (regression blast radius)."""
        return self._bfs(components, max_depth, reverse=True)

    def upstream(self, components: Iterable[str], max_depth: int = 3) -> dict[str, int]:
        """Components the changed ones rely on."""
        return self._bfs(components, max_depth, reverse=False)

    def critical_paths(
        self, components: Iterable[str], max_paths: int = 6, cutoff: int = 4
    ) -> list[list[str]]:
        """Highest-propagation paths from an entry point into a changed component."""
        seeds = [c for c in components if c in self.graph]
        if not seeds:
            return []
        entry_points = [
            node for node in self.graph.nodes if self.graph.in_degree(node) == 0
        ] or [node for node in self.graph.nodes if self.graph.in_degree(node) <= 1]
        scored: list[tuple[float, list[str]]] = []
        for entry in entry_points:
            for seed in seeds:
                if entry == seed:
                    continue
                try:
                    paths = nx.all_simple_paths(self.graph, entry, seed, cutoff=cutoff)
                    for path in paths:
                        score = 1.0
                        for left, right in zip(path, path[1:]):
                            score *= self.graph.edges[left, right].get("propagation", 0.5)
                        crit = CRITICALITY_WEIGHT.get(
                            self.graph.nodes[seed].get("business_criticality", "MEDIUM"), 0.5
                        )
                        scored.append((score * crit, path))
                except (nx.NetworkXNoPath, nx.NodeNotFound):  # pragma: no cover
                    continue
        scored.sort(key=lambda item: item[0], reverse=True)
        unique: list[list[str]] = []
        for _, path in scored:
            if path not in unique:
                unique.append(path)
            if len(unique) >= max_paths:
                break
        return unique

    def propagation_scores(
        self, components: Iterable[str], max_depth: int = 3
    ) -> dict[str, float]:
        """Decayed change-propagation strength per downstream component (0..1)."""
        reverse = self.graph.reverse(copy=False)
        scores: dict[str, float] = {}
        frontier: list[tuple[str, float]] = [(c, 1.0) for c in components if c in self.graph]
        seen = {c for c, _ in frontier}
        depth = 0
        while frontier and depth < max_depth:
            depth += 1
            next_frontier: list[tuple[str, float]] = []
            for node, strength in frontier:
                for neighbour in reverse.successors(node):
                    propagation = reverse.edges[node, neighbour].get("propagation", 0.5)
                    value = strength * propagation
                    if value <= scores.get(neighbour, 0.0):
                        continue
                    scores[neighbour] = round(value, 4)
                    if neighbour not in seen:
                        seen.add(neighbour)
                    next_frontier.append((neighbour, value))
            frontier = next_frontier
        return scores

    def node(self, component_id: str) -> dict[str, Any]:
        return dict(self.graph.nodes.get(component_id, {}))

    def subgraph_payload(self, components: Iterable[str], max_depth: int = 2) -> dict[str, Any]:
        """Nodes+edges for the UI dependency visualisation."""
        seeds = {c for c in components if c in self.graph}
        include = set(seeds)
        include |= set(self.downstream(seeds, max_depth))
        include |= set(self.upstream(seeds, max_depth))
        nodes = [
            {**self.node(node_id), "component_id": node_id, "seed": node_id in seeds}
            for node_id in include
        ]
        edges = [
            {
                "source": source,
                "target": target,
                **{k: v for k, v in data.items() if k != "description"},
            }
            for source, target, data in self.graph.edges(data=True)
            if source in include and target in include
        ]
        return {"nodes": nodes, "edges": edges}

    def stats(self) -> dict[str, Any]:
        return {
            "nodes": self.graph.number_of_nodes(),
            "edges": self.graph.number_of_edges(),
            "density": round(nx.density(self.graph), 4) if self.graph.number_of_nodes() else 0.0,
            "is_dag": nx.is_directed_acyclic_graph(self.graph),
        }


def build_dependency_graph(db: Session) -> DependencyGraphService:
    """Build a fresh graph. Cheap enough (tens of nodes) to do per workflow."""
    return DependencyGraphService().load(db)
