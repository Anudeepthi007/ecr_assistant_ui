"""Enumerations and small shared schemas."""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class ChangeType(str, Enum):
    UI = "UI_CHANGE"
    BACKEND = "BACKEND_CHANGE"
    API = "API_CHANGE"
    DATABASE = "DATABASE_CHANGE"
    INFRASTRUCTURE = "INFRASTRUCTURE_CHANGE"
    SECURITY = "SECURITY_CHANGE"
    CONFIGURATION = "CONFIGURATION_CHANGE"
    INTEGRATION = "INTEGRATION_CHANGE"
    MIXED = "MIXED_CHANGE"
    API_AND_BACKEND = "API_AND_BACKEND"


class Priority(str, Enum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"

    @classmethod
    def from_score(cls, score: float) -> "Priority":
        if score >= 90:
            return cls.P0
        if score >= 75:
            return cls.P1
        if score >= 50:
            return cls.P2
        return cls.P3


class AgentStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class WorkflowStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    REJECTED = "REJECTED"


class ConfidenceBand(str, Enum):
    LOW = "LOW CONFIDENCE"
    MEDIUM = "MEDIUM CONFIDENCE"
    HIGH = "HIGH CONFIDENCE"

    @classmethod
    def from_score(cls, score: float) -> "ConfidenceBand":
        if score >= 0.85:
            return cls.HIGH
        if score >= 0.65:
            return cls.MEDIUM
        return cls.LOW


class ScoredItem(BaseModel):
    """Generic id/score/reason triple used across agent outputs."""

    id: str
    title: str = ""
    score: float = Field(0.0, ge=0.0, le=100.0)
    reason: str = ""
