"""Enterprise source-system integration interfaces.

The platform reads its data through these interfaces so a real connector can be
dropped in without touching an agent. Every interface ships with a local
implementation (the seeded database) so the PoC needs no credentials, and a
placeholder adapter that documents exactly what the real one must return.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(slots=True)
class SourceSystem:
    """Describes a connected (or connectable) system for the UI and /health."""

    key: str
    name: str
    kind: str  # REQUIREMENTS | DEFECTS | TESTS | CODE | DOCS | WORKFLOW
    connected: bool
    detail: str = ""


class BaseRequirementProvider(ABC):
    """Requirements, from wherever the organisation keeps them."""

    key: str = "base"
    name: str = "Base requirement provider"

    @abstractmethod
    def fetch(self, *, query: str = "", ids: Iterable[str] = ()) -> list[dict[str, Any]]: ...

    def describe(self) -> SourceSystem:
        return SourceSystem(self.key, self.name, "REQUIREMENTS", connected=False)


class BaseDefectProvider(ABC):
    key: str = "base"
    name: str = "Base defect provider"

    @abstractmethod
    def fetch(self, *, query: str = "", components: Iterable[str] = ()) -> list[dict[str, Any]]: ...

    def describe(self) -> SourceSystem:
        return SourceSystem(self.key, self.name, "DEFECTS", connected=False)


class BaseTestProvider(ABC):
    key: str = "base"
    name: str = "Base test provider"

    @abstractmethod
    def fetch(
        self, *, requirement_ids: Iterable[str] = (), components: Iterable[str] = ()
    ) -> list[dict[str, Any]]: ...

    def describe(self) -> SourceSystem:
        return SourceSystem(self.key, self.name, "TESTS", connected=False)


class BaseRepositoryProvider(ABC):
    """Source control: which files a change actually touched."""

    key: str = "base"
    name: str = "Base repository provider"

    @abstractmethod
    def changed_files(self, reference: str) -> list[str]: ...

    def describe(self) -> SourceSystem:
        return SourceSystem(self.key, self.name, "CODE", connected=False)
