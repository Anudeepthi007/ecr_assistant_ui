"""How sure an analysis run is, from its steps' own confidence values."""
from __future__ import annotations

from typing import Any


def compute_confidence(
    per_step: dict[str, float], *, errors: list[dict[str, Any]] | None = None
) -> tuple[float, list[str]]:
    """Blend the step confidences and apply penalties for degraded execution."""
    penalties: list[str] = []
    values = [v for v in per_step.values() if v is not None]
    base = sum(values) / len(values) if values else 0.5
    for error in errors or []:
        agent = error.get("agent", "an agent")
        base -= 0.08
        penalties.append(f"{agent} failed - dependent evidence is missing")
    if len(values) < 5:
        base -= 0.05
        penalties.append("Fewer than five agents contributed evidence")
    return round(max(0.05, min(1.0, base)), 3), penalties
