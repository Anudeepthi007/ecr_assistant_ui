"""Guardrail: the platform has exactly three agents, and nothing else poses as one."""
from __future__ import annotations

import pkgutil

from app.agents import nodes
from app.agents.nodes.agents import AGENTS
from app.agents.orchestrator import get_compiled_graph
from app.agents.state import AGENT_CATALOG, AGENT_STEPS

AGENT_NAMES = {"Retrieval Agent", "Correlation Agent", "Summarization Agent"}


def test_catalogue_lists_exactly_three_agents():
    assert [a.name for a in AGENT_CATALOG] == [
        "Retrieval Agent",
        "Correlation Agent",
        "Summarization Agent",
    ]
    assert set(AGENT_STEPS) == {a.key for a in AGENT_CATALOG}


def test_graph_has_three_agent_nodes_plus_one_checkpoint():
    graph_nodes = set(get_compiled_graph().get_graph().nodes) - {"__start__", "__end__"}
    assert graph_nodes == {a.key for a in AGENT_CATALOG} | {"human_approval"}
    assert len(AGENTS) == 3


def test_every_step_is_owned_by_one_of_the_three_agents():
    import importlib
    import inspect

    for module_info in pkgutil.iter_modules(nodes.__path__):
        module = importlib.import_module(f"app.agents.nodes.{module_info.name}")
        for _, fn in inspect.getmembers(module, inspect.isfunction):
            if hasattr(fn, "step_name"):
                assert fn.step_name in AGENT_NAMES, f"{fn.step_key} is labelled {fn.step_name!r}"
                assert not fn.step_key.endswith("_agent")


def test_no_step_module_is_named_as_an_agent():
    names = {m.name for m in pkgutil.iter_modules(nodes.__path__)}
    assert not [n for n in names if n.endswith("_agent") or n.endswith("_agents")]


def test_the_three_agents_run_five_steps():
    assert [step["key"] for steps in AGENT_STEPS.values() for step in steps] == [
        "understand_ecr",
        "gather_evidence",
        "assess_impact",
        "select_tests",
        "summarize",
    ]
