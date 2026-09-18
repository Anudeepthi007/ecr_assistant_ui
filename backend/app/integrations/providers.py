"""Local providers (used by the PoC) and enterprise adapters (placeholders).

The local providers are the ones actually wired in: they read the seeded
database, which is what makes the platform runnable with no credentials. The
Azure DevOps / Jira / TestRail / GitHub adapters implement the same interfaces
and raise a clear error until they are configured, so the wiring point is
obvious and the failure is never silent.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any, Iterable

from app.config import settings
from app.database import session_scope
from app.integrations.base import (
    BaseDefectProvider,
    BaseRepositoryProvider,
    BaseRequirementProvider,
    BaseTestProvider,
    SourceSystem,
)
from app.logging import get_logger
from app.repositories import DefectRepository, RequirementRepository, TestRepository

logger = get_logger("ecr.integrations")


class NotConfigured(RuntimeError):
    """Raised when an enterprise adapter is used without credentials."""


# ---------------------------------------------------------------------------
# Local (seeded database) - the default wiring
# ---------------------------------------------------------------------------
class LocalRequirementProvider(BaseRequirementProvider):
    key = "local"
    name = "Local requirement store"

    def fetch(self, *, query: str = "", ids: Iterable[str] = ()) -> list[dict[str, Any]]:
        with session_scope() as db:
            repository = RequirementRepository(db)
            rows = repository.get_many(list(ids)) if ids else repository.list()
            return [row.as_dict() for row in rows]

    def describe(self) -> SourceSystem:
        return SourceSystem(self.key, self.name, "REQUIREMENTS", True, "CSV data files")


class LocalDefectProvider(BaseDefectProvider):
    key = "local"
    name = "Local defect store"

    def fetch(self, *, query: str = "", components: Iterable[str] = ()) -> list[dict[str, Any]]:
        with session_scope() as db:
            repository = DefectRepository(db)
            rows = repository.by_components(list(components)) if components else repository.list()
            return [row.as_dict() for row in rows]

    def describe(self) -> SourceSystem:
        return SourceSystem(self.key, self.name, "DEFECTS", True, "CSV data files")


class LocalTestProvider(BaseTestProvider):
    key = "local"
    name = "Local test store"

    def fetch(
        self, *, requirement_ids: Iterable[str] = (), components: Iterable[str] = ()
    ) -> list[dict[str, Any]]:
        with session_scope() as db:
            repository = TestRepository(db)
            rows: list = []
            if requirement_ids:
                rows += repository.by_requirements(list(requirement_ids))
            if components:
                rows += repository.by_components(list(components))
            if not rows:
                rows = repository.list()
            unique = {row.test_case_id: row for row in rows}
            return [row.as_dict() for row in unique.values()]

    def describe(self) -> SourceSystem:
        return SourceSystem(self.key, self.name, "TESTS", True, "CSV data files")


class LocalRepositoryProvider(BaseRepositoryProvider):
    key = "local"
    name = "Local sample repository"

    def changed_files(self, reference: str) -> list[str]:
        """The PoC takes changed files from the ECR record itself."""
        with session_scope() as db:
            from app.repositories import ECRRepository

            ecr = ECRRepository(db).get(reference)
            return list(ecr.changed_files or []) if ecr else []

    def describe(self) -> SourceSystem:
        return SourceSystem(self.key, self.name, "CODE", True, "Parsed with the Python AST analyzer")


# ---------------------------------------------------------------------------
# Enterprise adapters - interfaces implemented, credentials required
# ---------------------------------------------------------------------------
class AzureDevOpsRequirementProvider(BaseRequirementProvider):
    """Work items (`/_apis/wit/wiql`) mapped onto the requirement contract."""

    key = "azure_devops"
    name = "Azure DevOps Work Items"

    def __init__(self, organisation: str | None = None, project: str | None = None,
                 token: str | None = None) -> None:
        self.organisation = organisation
        self.project = project
        self.token = token

    @property
    def configured(self) -> bool:
        return bool(self.organisation and self.project and self.token)

    def fetch(self, *, query: str = "", ids: Iterable[str] = ()) -> list[dict[str, Any]]:
        if not self.configured:
            raise NotConfigured(
                "Azure DevOps is not configured. Provide organisation, project and a PAT, then map "
                "System.Id -> requirement_id, System.Title -> title, System.Description -> "
                "description, Microsoft.VSTS.Common.Priority -> priority."
            )
        raise NotConfigured("Azure DevOps client not implemented in this PoC")

    def describe(self) -> SourceSystem:
        return SourceSystem(
            self.key, self.name, "REQUIREMENTS", self.configured,
            "Interface ready; supply organisation/project/PAT to enable",
        )


class JiraRequirementProvider(BaseRequirementProvider):
    key = "jira"
    name = "Jira Issues"

    def __init__(self, base_url: str | None = None, token: str | None = None) -> None:
        self.base_url = base_url
        self.token = token

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.token)

    def fetch(self, *, query: str = "", ids: Iterable[str] = ()) -> list[dict[str, Any]]:
        raise NotConfigured("Jira client not implemented in this PoC")

    def describe(self) -> SourceSystem:
        return SourceSystem(self.key, self.name, "REQUIREMENTS", self.configured,
                            "Interface ready; supply base URL and API token")


class ServiceNowDefectProvider(BaseDefectProvider):
    key = "servicenow"
    name = "ServiceNow Incidents"

    def __init__(self, instance: str | None = None, token: str | None = None) -> None:
        self.instance = instance
        self.token = token

    @property
    def configured(self) -> bool:
        return bool(self.instance and self.token)

    def fetch(self, *, query: str = "", components: Iterable[str] = ()) -> list[dict[str, Any]]:
        raise NotConfigured("ServiceNow client not implemented in this PoC")

    def describe(self) -> SourceSystem:
        return SourceSystem(self.key, self.name, "DEFECTS", self.configured,
                            "Interface ready; supply instance and token")


class TestRailTestProvider(BaseTestProvider):
    key = "testrail"
    name = "TestRail Test Cases"

    def __init__(self, base_url: str | None = None, token: str | None = None) -> None:
        self.base_url = base_url
        self.token = token

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.token)

    def fetch(
        self, *, requirement_ids: Iterable[str] = (), components: Iterable[str] = ()
    ) -> list[dict[str, Any]]:
        raise NotConfigured("TestRail client not implemented in this PoC")

    def describe(self) -> SourceSystem:
        return SourceSystem(self.key, self.name, "TESTS", self.configured,
                            "Interface ready; supply base URL and API key")


class GitHubRepositoryProvider(BaseRepositoryProvider):
    key = "github"
    name = "GitHub Repositories"

    def __init__(self, token: str | None = None, repo: str | None = None) -> None:
        self.token = token
        self.repo = repo

    @property
    def configured(self) -> bool:
        return bool(self.token and self.repo)

    def changed_files(self, reference: str) -> list[str]:
        if not self.configured:
            raise NotConfigured(
                "GitHub is not configured. Provide a token and owner/repo, then read the file list "
                "from GET /repos/{owner}/{repo}/pulls/{number}/files."
            )
        raise NotConfigured("GitHub client not implemented in this PoC")

    def describe(self) -> SourceSystem:
        return SourceSystem(self.key, self.name, "CODE", self.configured,
                            "Interface ready; supply a token and owner/repo")


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------
def get_requirement_provider() -> BaseRequirementProvider:
    return LocalRequirementProvider()


def get_defect_provider() -> BaseDefectProvider:
    return LocalDefectProvider()


def get_test_provider() -> BaseTestProvider:
    return LocalTestProvider()


def get_repository_provider() -> BaseRepositoryProvider:
    return LocalRepositoryProvider()


def source_systems() -> list[dict[str, Any]]:
    """Everything the platform can read from, and whether it is connected."""
    providers = [
        LocalRequirementProvider(),
        LocalDefectProvider(),
        LocalTestProvider(),
        LocalRepositoryProvider(),
        AzureDevOpsRequirementProvider(),
        JiraRequirementProvider(),
        ServiceNowDefectProvider(),
        TestRailTestProvider(),
        GitHubRepositoryProvider(),
    ]
    return [asdict(provider.describe()) for provider in providers]
