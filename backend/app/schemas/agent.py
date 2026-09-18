"""Agent execution / workflow telemetry schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import AgentStatus, WorkflowStatus


class AgentDescriptor(BaseModel):
    """Static catalogue entry describing an agent in the graph."""

    key: str
    name: str
    purpose: str
    tools: list[str] = Field(default_factory=list)
    optional: bool = False
    depends_on: list[str] = Field(default_factory=list)


class AgentEvent(BaseModel):
    """A single event on the workflow event stream (also the execution trace)."""

    timestamp: datetime
    workflow_id: str
    ecr_id: str = ""
    agent: str
    agent_key: str = ""
    status: AgentStatus | WorkflowStatus | str
    action: str = ""
    detail: str = ""
    duration: float | None = None
    confidence: float | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class AgentRunRead(BaseModel):
    workflow_id: str
    ecr_id: str
    agent: str
    agent_key: str
    status: str
    action: str
    reasoning: str
    confidence: float
    execution_time: float
    error: str = ""
    timestamp: str | None = None
    output: dict[str, Any] = Field(default_factory=dict)


class WorkflowSummary(BaseModel):
    workflow_id: str
    ecr_id: str
    status: WorkflowStatus
    started_at: datetime
    finished_at: datetime | None = None
    duration: float = 0.0
    plan: list[str] = Field(default_factory=list)
    skipped_steps: list[str] = Field(default_factory=list)
    current_agent: str | None = None
    progress: float = 0.0
    confidence: float = 0.0
    errors: list[dict[str, Any]] = Field(default_factory=list)
    approval_required: bool = False
    approval_status: str = "NOT_REQUIRED"
    events: list[AgentEvent] = Field(default_factory=list)


class ApprovalDecision(BaseModel):
    approved: bool
    decided_by: str = "qa.lead@enterprise.com"
    comment: str = ""
    excluded_test_ids: list[str] = Field(default_factory=list)
