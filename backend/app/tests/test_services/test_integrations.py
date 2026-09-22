"""Source-system providers: local ones work, enterprise ones fail loudly."""
from __future__ import annotations

import pytest

from app.integrations.providers import (
    AzureDevOpsRequirementProvider,
    GitHubRepositoryProvider,
    LocalDefectProvider,
    LocalRequirementProvider,
    LocalTestProvider,
    NotConfigured,
    source_systems,
)


def test_local_requirement_provider_reads_the_corpus(database):
    rows = LocalRequirementProvider().fetch()
    assert len(rows) == 64
    subset = LocalRequirementProvider().fetch(ids=["REQ-1003", "L2R367"])
    assert {row["requirement_id"] for row in subset} == {"REQ-1003", "L2R367"}


def test_local_defect_provider_filters_by_component(database):
    rows = LocalDefectProvider().fetch(components=["CMP-004"])
    assert rows
    assert all(
        row["affected_component"] == "CMP-004" or "CMP-004" in row["related_components"]
        for row in rows
    )


def test_local_test_provider_filters_by_requirement(database):
    rows = LocalTestProvider().fetch(requirement_ids=["L2R367"])
    assert rows
    assert all(row["requirement_id"] == "L2R367" for row in rows)


def test_enterprise_adapters_fail_loudly_until_configured():
    with pytest.raises(NotConfigured):
        AzureDevOpsRequirementProvider().fetch()
    with pytest.raises(NotConfigured):
        GitHubRepositoryProvider().changed_files("PR-1")


def test_source_system_inventory_marks_what_is_connected(database):
    systems = source_systems()
    # several local providers share the "local" key, one per artifact kind
    local = [entry for entry in systems if entry["key"] == "local"]
    assert len(local) == 4 and all(entry["connected"] for entry in local)
    remote = [entry for entry in systems if entry["key"] != "local"]
    assert remote and not any(entry["connected"] for entry in remote)
    assert all(entry["kind"] and entry["name"] for entry in systems)
