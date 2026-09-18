"""Repositories - the only place that issues queries for a given aggregate."""
from __future__ import annotations

from sqlalchemy import desc, or_, select

from app.models import (
    AgentRun,
    Component,
    Defect,
    Dependency,
    ECR,
    Feedback,
    ImpactReport,
    Requirement,
    TestCase,
)
from app.repositories.base import BaseRepository


class ECRRepository(BaseRepository[ECR]):
    model = ECR
    key_field = "ecr_id"

    def recent(self, limit: int = 10) -> list[ECR]:
        return list(
            self.db.execute(select(ECR).order_by(desc(ECR.created_at)).limit(limit))
            .scalars()
            .all()
        )

    def search(self, term: str, limit: int = 20) -> list[ECR]:
        like = f"%{term.lower()}%"
        stmt = (
            select(ECR)
            .where(or_(ECR.ecr_id.ilike(like), ECR.title.ilike(like), ECR.description.ilike(like)))
            .limit(limit)
        )
        return list(self.db.execute(stmt).scalars().all())


class RequirementRepository(BaseRepository[Requirement]):
    model = Requirement
    key_field = "requirement_id"

    def by_component(self, component_id: str) -> list[Requirement]:
        return [
            row
            for row in self.list()
            if row.component == component_id or component_id in (row.linked_components or [])
        ]


class DefectRepository(BaseRepository[Defect]):
    model = Defect
    key_field = "defect_id"

    def by_components(self, component_ids: list[str]) -> list[Defect]:
        wanted = set(component_ids)
        return [
            row
            for row in self.list()
            if row.affected_component in wanted or wanted & set(row.related_components or [])
        ]


class TestRepository(BaseRepository[TestCase]):
    model = TestCase
    key_field = "test_case_id"

    def by_requirements(self, requirement_ids: list[str]) -> list[TestCase]:
        wanted = set(requirement_ids)
        return [row for row in self.list() if row.requirement_id in wanted]

    def by_components(self, component_ids: list[str]) -> list[TestCase]:
        wanted = set(component_ids)
        return [
            row
            for row in self.list()
            if row.component in wanted or wanted & set(row.linked_components or [])
        ]


class ComponentRepository(BaseRepository[Component]):
    model = Component
    key_field = "component_id"


class DependencyRepository(BaseRepository[Dependency]):
    model = Dependency
    key_field = "id"


class AgentRunRepository(BaseRepository[AgentRun]):
    model = AgentRun
    key_field = "workflow_id"

    def for_workflow(self, workflow_id: str) -> list[AgentRun]:
        return list(
            self.db.execute(
                select(AgentRun).where(AgentRun.workflow_id == workflow_id).order_by(AgentRun.id)
            )
            .scalars()
            .all()
        )

    def recent(self, limit: int = 50) -> list[AgentRun]:
        return list(
            self.db.execute(select(AgentRun).order_by(desc(AgentRun.id)).limit(limit))
            .scalars()
            .all()
        )


class ImpactReportRepository(BaseRepository[ImpactReport]):
    model = ImpactReport
    key_field = "ecr_id"

    def latest_for_ecr(self, ecr_id: str) -> ImpactReport | None:
        return (
            self.db.execute(
                select(ImpactReport)
                .where(ImpactReport.ecr_id == ecr_id)
                .order_by(desc(ImpactReport.id))
                .limit(1)
            )
            .scalars()
            .first()
        )

    def all_reports(self, limit: int = 200) -> list[ImpactReport]:
        return list(
            self.db.execute(select(ImpactReport).order_by(desc(ImpactReport.id)).limit(limit))
            .scalars()
            .all()
        )


class FeedbackRepository(BaseRepository[Feedback]):
    model = Feedback
    key_field = "ecr_id"


__all__ = [
    "AgentRunRepository",
    "ComponentRepository",
    "DefectRepository",
    "DependencyRepository",
    "ECRRepository",
    "FeedbackRepository",
    "ImpactReportRepository",
    "RequirementRepository",
    "TestRepository",
]
