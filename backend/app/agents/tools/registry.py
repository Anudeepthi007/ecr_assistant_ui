"""Tool registry.

Every capability an agent can invoke is registered here, which gives the UI an
honest list of the tools each agent actually called (agent transparency) and
keeps tool implementations independent of the graph.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(slots=True)
class ToolSpec:
    name: str
    description: str
    func: Callable[..., Any]


TOOLS: dict[str, ToolSpec] = {}


def tool(name: str, description: str) -> Callable:
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        TOOLS[name] = ToolSpec(name=name, description=description, func=func)
        func.tool_name = name  # type: ignore[attr-defined]
        return func

    return decorator


def list_tools() -> list[dict[str, str]]:
    return [{"name": spec.name, "description": spec.description} for spec in TOOLS.values()]


def call_tool(name: str, *args: Any, **kwargs: Any) -> Any:
    spec = TOOLS.get(name)
    if spec is None:
        raise KeyError(f"unknown tool: {name}")
    return spec.func(*args, **kwargs)
