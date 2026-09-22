"""Tools for retrieving human artifacts: review comments and evidence.

These are the sources a user would otherwise open one by one (work item
discussions, review threads, test evidence folders).
"""
from __future__ import annotations

from typing import Any, Iterable

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.agents.tools.registry import tool
from app.models import Comment, Evidence


@tool("comments_for_ecr", "Fetch every review comment attached to an ECR or its linked artifacts.")
def comments_for_ecr(
    db: Session, ecr_id: str, *, related_ids: Iterable[str] = ()
) -> list[dict[str, Any]]:
    related = [rid for rid in related_ids if rid]
    stmt = select(Comment).where(
        or_(Comment.ecr_id == ecr_id, Comment.target_id.in_(related) if related else False)
    )
    rows = db.execute(stmt).scalars().all()
    return sorted(
        (row.as_dict() for row in rows),
        key=lambda item: item.get("created_at") or "",
        reverse=True,
    )


@tool("evidence_for_ecr", "Fetch evidence artifacts (runs, reviews, documents) for an ECR.")
def evidence_for_ecr(
    db: Session, ecr_id: str, *, related_ids: Iterable[str] = ()
) -> list[dict[str, Any]]:
    related = [rid for rid in related_ids if rid]
    stmt = select(Evidence).where(
        or_(Evidence.ecr_id == ecr_id, Evidence.target_id.in_(related) if related else False)
    )
    rows = db.execute(stmt).scalars().all()
    return sorted(
        (row.as_dict() for row in rows),
        key=lambda item: item.get("captured_at") or "",
        reverse=True,
    )


@tool("extract_comment_signals", "Pull decisions, risks and scope calls out of a comment thread.")
def extract_comment_signals(comments: list[dict[str, Any]]) -> dict[str, list[dict[str, str]]]:
    signals: dict[str, list[dict[str, str]]] = {
        "decisions": [],
        "risks": [],
        "scope": [],
        "test_scope": [],
        "implementation": [],
    }
    bucket_by_category = {
        "DECISION": "decisions",
        "RISK": "risks",
        "SCOPE": "scope",
        "TEST_SCOPE": "test_scope",
        "IMPLEMENTATION": "implementation",
        "HISTORY": "risks",
    }
    for comment in comments:
        bucket = bucket_by_category.get(comment.get("category", ""), None)
        if bucket is None:
            continue
        signals[bucket].append(
            {
                "comment_id": comment.get("comment_id", ""),
                "author": comment.get("author", ""),
                "role": comment.get("author_role", ""),
                "text": comment.get("body", ""),
                "references": comment.get("references", []),
            }
        )
    return signals


@tool("evidence_gaps", "Identify artifacts that have no supporting evidence yet.")
def evidence_gaps(evidence: list[dict[str, Any]], expected_targets: Iterable[str]) -> list[str]:
    covered = {item.get("target_id") for item in evidence if item.get("target_id")}
    return sorted({target for target in expected_targets if target and target not in covered})
