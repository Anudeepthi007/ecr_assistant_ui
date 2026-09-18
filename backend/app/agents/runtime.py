"""Workflow runtime: live run registry, event stream and the agent-node decorator.

Nodes execute inside LangGraph's worker threads, so the registry is guarded by a
lock and the SSE endpoint simply tails an append-only event list. That keeps the
streaming path free of cross-thread asyncio hand-offs.
"""
from __future__ import annotations

import functools
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from app.config import settings
from app.database import session_scope
from app.logging import get_logger
from app.models import AgentRun
from app.schemas.agent import AgentEvent
from app.schemas.common import AgentStatus, WorkflowStatus

logger = get_logger("ecr.runtime")


class WorkflowRun:
    """Live state of one analysis run."""

    def __init__(self, workflow_id: str, ecr_id: str, options: dict[str, Any]) -> None:
        self.workflow_id = workflow_id
        self.ecr_id = ecr_id
        self.options = options
        self.status: WorkflowStatus = WorkflowStatus.QUEUED
        self.started_at = datetime.now(timezone.utc)
        self.finished_at: datetime | None = None
        self.events: list[AgentEvent] = []
        self.plan: list[str] = []
        self.skipped: list[str] = []
        self.current_agent: str | None = None
        self.errors: list[dict[str, Any]] = []
        self.state: dict[str, Any] = {}
        self.report: dict[str, Any] | None = None
        self.confidence: float = 0.0
        self.approval_required = False
        self.approval_status = "NOT_REQUIRED"
        self.approval_decision: dict[str, Any] | None = None
        self._lock = threading.Lock()
        self._approval_event = threading.Event()

    # -- events -----------------------------------------------------------
    def emit(self, event: AgentEvent) -> None:
        with self._lock:
            self.events.append(event)

    def events_after(self, index: int) -> tuple[int, list[AgentEvent]]:
        with self._lock:
            return len(self.events), self.events[index:]

    @property
    def duration(self) -> float:
        end = self.finished_at or datetime.now(timezone.utc)
        return round((end - self.started_at).total_seconds(), 2)

    @property
    def progress(self) -> float:
        if not self.plan:
            return 0.05
        done = {
            event.agent_key
            for event in self.events
            if event.status in (AgentStatus.COMPLETED, AgentStatus.FAILED, AgentStatus.SKIPPED)
        }
        return round(min(1.0, len(done & set(self.plan)) / max(len(self.plan), 1)), 3)

    # -- human in the loop -------------------------------------------------
    def request_approval(self) -> None:
        self.approval_required = True
        self.approval_status = "PENDING"
        self.status = WorkflowStatus.AWAITING_APPROVAL
        self._approval_event.clear()

    def wait_for_approval(self, timeout: float) -> bool:
        return self._approval_event.wait(timeout)

    def resolve_approval(self, decision: dict[str, Any]) -> None:
        self.approval_decision = decision
        self.approval_status = "APPROVED" if decision.get("approved") else "REJECTED"
        self._approval_event.set()

    def summary(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "ecr_id": self.ecr_id,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration": self.duration,
            "plan": self.plan,
            "skipped_steps": self.skipped,
            "current_agent": self.current_agent,
            "progress": self.progress,
            "confidence": self.confidence,
            "errors": self.errors,
            "approval_required": self.approval_required,
            "approval_status": self.approval_status,
            "events": self.events,
        }


class WorkflowRegistry:
    """Process-wide registry of runs (bounded, newest wins)."""

    MAX_RUNS = 100

    def __init__(self) -> None:
        self._runs: dict[str, WorkflowRun] = {}
        self._by_ecr: dict[str, str] = {}
        self._lock = threading.Lock()

    def create(self, ecr_id: str, options: dict[str, Any]) -> WorkflowRun:
        workflow_id = f"WF-{uuid.uuid4().hex[:12]}"
        run = WorkflowRun(workflow_id, ecr_id, options)
        with self._lock:
            self._runs[workflow_id] = run
            self._by_ecr[ecr_id] = workflow_id
            if len(self._runs) > self.MAX_RUNS:
                oldest = sorted(self._runs.values(), key=lambda r: r.started_at)[0]
                self._runs.pop(oldest.workflow_id, None)
        return run

    def get(self, workflow_id: str) -> WorkflowRun | None:
        return self._runs.get(workflow_id)

    def latest_for_ecr(self, ecr_id: str) -> WorkflowRun | None:
        workflow_id = self._by_ecr.get(ecr_id)
        return self._runs.get(workflow_id) if workflow_id else None

    def all(self) -> list[WorkflowRun]:
        return sorted(self._runs.values(), key=lambda r: r.started_at, reverse=True)


registry = WorkflowRegistry()


def emit_event(
    workflow_id: str,
    *,
    agent: str,
    agent_key: str,
    status: Any,
    action: str = "",
    detail: str = "",
    duration: float | None = None,
    confidence: float | None = None,
    payload: dict[str, Any] | None = None,
    ecr_id: str = "",
) -> AgentEvent:
    event = AgentEvent(
        timestamp=datetime.now(timezone.utc),
        workflow_id=workflow_id,
        ecr_id=ecr_id,
        agent=agent,
        agent_key=agent_key,
        status=status,
        action=action,
        detail=detail,
        duration=duration,
        confidence=confidence,
        payload=payload or {},
    )
    run = registry.get(workflow_id)
    if run:
        run.emit(event)
    return event


def persist_agent_run(
    *,
    workflow_id: str,
    ecr_id: str,
    agent_name: str,
    agent_key: str,
    status: str,
    action: str,
    output: dict[str, Any],
    reasoning: str,
    confidence: float,
    execution_time: float,
    error: str = "",
) -> None:
    try:
        with session_scope() as db:
            db.add(
                AgentRun(
                    workflow_id=workflow_id,
                    ecr_id=ecr_id,
                    agent_name=agent_name,
                    agent_key=agent_key,
                    status=status,
                    action=action,
                    input={},
                    output=output,
                    reasoning=reasoning,
                    confidence=confidence,
                    execution_time=execution_time,
                    error=error,
                )
            )
    except Exception as exc:  # pragma: no cover - telemetry must never break a run
        logger.warning("runtime.persist_failed", agent=agent_name, error=str(exc))


def agent_node(
    key: str,
    name: str,
    action: str,
    *,
    critical: bool = False,
    output_keys: tuple[str, ...] = (),
) -> Callable:
    """Decorate a node function with tracing, timing and graceful degradation.

    A failing non-critical agent records the error, emits a ``failed`` event and
    returns an empty partial state so the graph keeps going with reduced
    confidence. A failing critical agent re-raises.
    """

    def decorator(func: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
        @functools.wraps(func)
        def wrapper(state: dict[str, Any], *args: Any, **kwargs: Any) -> dict[str, Any]:
            workflow_id = state.get("workflow_id", "")
            ecr_id = state.get("ecr_id", "")
            run = registry.get(workflow_id)
            if run:
                run.current_agent = name
                if run.status == WorkflowStatus.QUEUED:
                    run.status = WorkflowStatus.RUNNING
            emit_event(
                workflow_id,
                agent=name,
                agent_key=key,
                status=AgentStatus.RUNNING,
                action=action,
                ecr_id=ecr_id,
            )
            started = time.perf_counter()
            if settings.agent_step_delay_ms:
                time.sleep(settings.agent_step_delay_ms / 1000.0)
            try:
                result = func(state, *args, **kwargs) or {}
            except Exception as exc:
                duration = round(time.perf_counter() - started, 3)
                logger.exception("agent.failed", agent=name, workflow_id=workflow_id)
                error = {"agent": name, "agent_key": key, "error": str(exc), "critical": critical}
                if run:
                    run.errors.append(error)
                emit_event(
                    workflow_id,
                    agent=name,
                    agent_key=key,
                    status=AgentStatus.FAILED,
                    action=action,
                    detail=str(exc),
                    duration=duration,
                    ecr_id=ecr_id,
                )
                persist_agent_run(
                    workflow_id=workflow_id,
                    ecr_id=ecr_id,
                    agent_name=name,
                    agent_key=key,
                    status="FAILED",
                    action=action,
                    output={},
                    reasoning="",
                    confidence=0.0,
                    execution_time=duration,
                    error=str(exc),
                )
                if critical:
                    raise
                return {
                    "errors": [error],
                    "execution_trace": [
                        _trace(name, key, action, "failed", duration, detail=str(exc))
                    ],
                    "skipped_steps": [key],
                }

            duration = round(time.perf_counter() - started, 3)
            confidence = float(result.get("_confidence", 0.0) or 0.0)
            reasoning = str(result.get("_reasoning", ""))
            summary = result.get("_summary", {})
            result.pop("_confidence", None)
            result.pop("_reasoning", None)
            result.pop("_summary", None)

            emit_event(
                workflow_id,
                agent=name,
                agent_key=key,
                status=AgentStatus.COMPLETED,
                action=action,
                detail=reasoning[:400],
                duration=duration,
                confidence=confidence,
                payload=summary,
                ecr_id=ecr_id,
            )
            persist_agent_run(
                workflow_id=workflow_id,
                ecr_id=ecr_id,
                agent_name=name,
                agent_key=key,
                status="COMPLETED",
                action=action,
                output=summary,
                reasoning=reasoning,
                confidence=confidence,
                execution_time=duration,
            )
            trace = _trace(name, key, action, "completed", duration, detail=reasoning[:400])
            trace["confidence"] = confidence
            trace["summary"] = summary
            merged: dict[str, Any] = dict(result)
            merged["execution_trace"] = [*(merged.get("execution_trace") or []), trace]
            if confidence:
                merged["step_confidence"] = {**merged.get("step_confidence", {}), key: confidence}
            return merged

        wrapper.agent_key = key  # type: ignore[attr-defined]
        wrapper.agent_name = name  # type: ignore[attr-defined]
        return wrapper

    return decorator


def agent_step(key: str, name: str, action: str, *, critical: bool = False) -> Callable:
    """Decorate an internal step of an agent.

    Steps are the units of work inside the three top-level agents. They emit
    their own start/finish events (so the UI can show progress *inside* an
    agent) and degrade gracefully: a failing non-critical step records the
    error and returns an empty partial state instead of aborting the agent.
    """

    def decorator(func: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
        @functools.wraps(func)
        def wrapper(state: dict[str, Any], *args: Any, **kwargs: Any) -> dict[str, Any]:
            workflow_id = state.get("workflow_id", "")
            ecr_id = state.get("ecr_id", "")
            emit_event(
                workflow_id,
                agent=name,
                agent_key=key,
                status=AgentStatus.RUNNING,
                action=action,
                ecr_id=ecr_id,
                payload={"step": True},
            )
            started = time.perf_counter()
            if settings.agent_step_delay_ms:
                time.sleep(settings.agent_step_delay_ms / 1000.0)
            try:
                result = func(state, *args, **kwargs) or {}
            except Exception as exc:
                duration = round(time.perf_counter() - started, 3)
                logger.exception("step.failed", step=name, workflow_id=workflow_id)
                error = {"agent": name, "agent_key": key, "error": str(exc), "critical": critical}
                run = registry.get(workflow_id)
                if run:
                    run.errors.append(error)
                emit_event(
                    workflow_id,
                    agent=name,
                    agent_key=key,
                    status=AgentStatus.FAILED,
                    action=action,
                    detail=str(exc),
                    duration=duration,
                    ecr_id=ecr_id,
                    payload={"step": True},
                )
                persist_agent_run(
                    workflow_id=workflow_id,
                    ecr_id=ecr_id,
                    agent_name=name,
                    agent_key=key,
                    status="FAILED",
                    action=action,
                    output={},
                    reasoning="",
                    confidence=0.0,
                    execution_time=duration,
                    error=str(exc),
                )
                if critical:
                    raise
                return {
                    "errors": [error],
                    "execution_trace": [
                        _trace(name, key, action, "failed", duration, detail=str(exc))
                    ],
                    "skipped_steps": [key],
                }

            duration = round(time.perf_counter() - started, 3)
            confidence = float(result.pop("_confidence", 0.0) or 0.0)
            reasoning = str(result.pop("_reasoning", ""))
            summary = result.pop("_summary", {})
            emit_event(
                workflow_id,
                agent=name,
                agent_key=key,
                status=AgentStatus.COMPLETED,
                action=action,
                detail=reasoning[:400],
                duration=duration,
                confidence=confidence,
                payload={**summary, "step": True},
                ecr_id=ecr_id,
            )
            persist_agent_run(
                workflow_id=workflow_id,
                ecr_id=ecr_id,
                agent_name=name,
                agent_key=key,
                status="COMPLETED",
                action=action,
                output=summary,
                reasoning=reasoning,
                confidence=confidence,
                execution_time=duration,
            )
            trace = _trace(name, key, action, "completed", duration, detail=reasoning[:400])
            trace["confidence"] = confidence
            trace["summary"] = summary
            merged = dict(result)
            merged["execution_trace"] = [*(merged.get("execution_trace") or []), trace]
            if confidence:
                merged["step_confidence"] = {**merged.get("step_confidence", {}), key: confidence}
            return merged

        wrapper.step_key = key  # type: ignore[attr-defined]
        wrapper.step_name = name  # type: ignore[attr-defined]
        return wrapper

    return decorator


def build_view(state: dict[str, Any], accumulated: dict[str, Any]) -> dict[str, Any]:
    """State as a step should see it: incoming state plus what was produced so far.

    Applies the same reducers LangGraph applies between nodes. A plain
    ``{**state, **accumulated}`` would let partial trace and confidence *replace*
    what earlier agents contributed, so a step reading the whole run (the report)
    would only ever see its own agent.
    """
    view = dict(state)
    for key, value in accumulated.items():
        if key.startswith("_"):
            continue
        if key in ("execution_trace", "errors"):
            view[key] = [*(state.get(key) or []), *(value or [])]
        elif key == "skipped_steps":
            merged = list(state.get(key) or [])
            merged += [item for item in (value or []) if item not in merged]
            view[key] = merged
        elif key in ("step_confidence", "tools_used"):
            view[key] = {**(state.get(key) or {}), **(value or {})}
        else:
            view[key] = value
    return view


def merge_partial(target: dict[str, Any], partial: dict[str, Any]) -> dict[str, Any]:
    """Merge a step result into an accumulating agent result.

    Mirrors the LangGraph reducers: additive keys concatenate, dict keys merge,
    everything else is last-write-wins.
    """
    for key, value in (partial or {}).items():
        if key in ("execution_trace", "errors", "skipped_steps"):
            existing = list(target.get(key) or [])
            for item in value or []:
                if key == "skipped_steps" and item in existing:
                    continue
                existing.append(item)
            target[key] = existing
        elif key in ("step_confidence", "tools_used"):
            target[key] = {**(target.get(key) or {}), **(value or {})}
        else:
            target[key] = value
    return target


def _trace(
    name: str, key: str, action: str, status: str, duration: float, detail: str = ""
) -> dict[str, Any]:
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agent": name,
        "agent_key": key,
        "action": action,
        "status": status,
        "duration": duration,
        "detail": detail,
    }
