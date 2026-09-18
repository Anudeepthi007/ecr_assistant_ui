"""What belongs to an ECR.

Every change record names its own scope: the requirements it links and the
test cases it lists as affected. The analysis uses only that scope - the
linked requirements, the listed tests (and the tests traced to those
requirements), the defects raised against those requirements, the components
those requirements name, and the comments and evidence attached to the ECR
itself. There is no keyword, semantic or component-wide widening, so the page
shows only data that belongs to that ECR.

Similarity is still used to score and order what is in scope; it never adds
anything. An ECR created without any linked requirement or test falls back to
the broader search, because it has no scope of its own yet.
"""
from __future__ import annotations

from typing import Any


def is_scoped(ecr: dict[str, Any] | None) -> bool:
    ecr = ecr or {}
    return bool(ecr.get("affected_test_cases") or ecr.get("linked_requirements"))


def listed_test_ids(ecr: dict[str, Any] | None) -> list[str]:
    """Affected test cases named on the ECR ("L2R26: TC2" -> "L2R26:TC2")."""
    return [
        "".join(str(value).split())
        for value in (ecr or {}).get("affected_test_cases") or []
        if str(value).strip()
    ]


def linked_requirement_ids(ecr: dict[str, Any] | None) -> set[str]:
    """Linked requirements, plus the requirement named in an "L2R26:TC1" style test id."""
    linked = {str(value).strip() for value in (ecr or {}).get("linked_requirements") or [] if str(value).strip()}
    linked |= {test_id.split(":", 1)[0] for test_id in listed_test_ids(ecr) if ":" in test_id}
    return linked
