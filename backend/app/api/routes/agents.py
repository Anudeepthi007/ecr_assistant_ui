"""Agent catalogue, tool registry and execution telemetry."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.agents.orchestrator import graph_topology
from app.agents.state import AGENT_CATALOG, AGENT_STEPS
from app.agents.tools import (  # noqa: F401  (imports register the tools)
    code_tools,
    collaboration_tools,
    defect_tools,
    dependency_tools,
    requirement_tools,
    test_tools,
)
from app.agents.tools.registry import list_tools
from app.dependencies import DbSession
from app.repositories import AgentRunRepository

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("")
def list_agents() -> dict[str, Any]:
    """The three agents, their purpose, tools and internal steps."""
    return {
        "agents": [
            {**descriptor.model_dump(), "steps": AGENT_STEPS.get(descriptor.key, [])}
            for descriptor in AGENT_CATALOG
        ],
        "topology": graph_topology(),
    }


@router.get("/tools")
def tools() -> dict[str, Any]:
    # Importing the node modules registers the tools they define locally.
    from app.agents.nodes import correlation, ecr_understanding, planning  # noqa: F401

    return {"tools": list_tools()}


@router.get("/runs")
def agent_runs(
    db: DbSession,
    workflow_id: str | None = None,
    limit: int = Query(60, le=300),
) -> list[dict[str, Any]]:
    repository = AgentRunRepository(db)
    rows = repository.for_workflow(workflow_id) if workflow_id else repository.recent(limit)
    return [row.as_dict() for row in rows]
