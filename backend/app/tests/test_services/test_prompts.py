"""Every prompt lives in app/prompts.py, and every placeholder is still filled in."""
from __future__ import annotations

import re

import pytest

from app import prompts
from app.agents.nodes import correlation_review, retrieval_planning, summarization
from app.llm import base
from app.services import chat_service

# Template -> the placeholders the agent that owns it supplies. Renaming one on
# either side breaks this test instead of the analysis.
TEMPLATES = {
    "RETRIEVAL_TASK": {
        "ecr_id",
        "title",
        "description",
        "steps_to_reproduce",
        "observed_behavior",
        "expected_behavior",
        "changed_files",
        "linked_requirements",
        "classification",
        "max_terms",
        "max_behaviours",
    },
    "CORRELATION_TASK": {"bundle", "rule_findings", "max_findings"},
    "SUMMARY_TASK": {"question", "bundle", "defect_instruction"},
    "SUMMARY_DEFECT_INSTRUCTION": {"ecr_id"},
    "NARRATION_TASK": {"task", "context", "fallback"},
    "CHAT_TASK": {"question", "ecr_id", "bundle", "focus"},
    "CHAT_FOCUS": {"focus"},
}

SYSTEM_PROMPTS = [
    "RETRIEVAL_SYSTEM_PROMPT",
    "CORRELATION_SYSTEM_PROMPT",
    "ANSWER_SYSTEM_PROMPT",
    "NARRATION_SYSTEM_PROMPT",
]


def _placeholders(template: str) -> set[str]:
    """Single-brace fields only; a doubled brace is literal text, not a placeholder."""
    return {match.group(1) for match in re.finditer(r"(?<!\{)\{([a-z_]+)\}(?!\})", template)}


@pytest.mark.parametrize("name,expected", sorted(TEMPLATES.items()))
def test_each_template_declares_the_placeholders_its_agent_fills(name, expected):
    template = getattr(prompts, name)
    assert _placeholders(template) == expected
    filled = template.format(**{key: f"<{key}>" for key in expected})
    assert all(f"<{key}>" in filled for key in expected)


@pytest.mark.parametrize("name", SYSTEM_PROMPTS)
def test_every_system_prompt_has_text(name):
    assert getattr(prompts, name).strip()


def test_the_correlation_json_example_survives_formatting():
    """Its braces are doubled in the file; the model must still see real JSON."""
    filled = prompts.CORRELATION_TASK.format(bundle="{}", rule_findings="{}", max_findings=4)
    assert '{"ids": [...], "text": "one sentence under 30 words"}' in filled


def test_no_agent_keeps_its_own_copy_of_a_prompt():
    """Each caller must use the shared text, so editing prompts.py changes the run."""
    assert retrieval_planning.RETRIEVAL_SYSTEM_PROMPT is prompts.RETRIEVAL_SYSTEM_PROMPT
    assert correlation_review.CORRELATION_SYSTEM_PROMPT is prompts.CORRELATION_SYSTEM_PROMPT
    assert summarization.ANSWER_SYSTEM_PROMPT is prompts.ANSWER_SYSTEM_PROMPT
    assert summarization.SUMMARY_STYLE is prompts.SUMMARY_STYLE
    assert chat_service.ANSWER_SYSTEM_PROMPT is prompts.ANSWER_SYSTEM_PROMPT
    assert base.NARRATION_SYSTEM_PROMPT is prompts.NARRATION_SYSTEM_PROMPT


def test_the_mock_provider_markers_stay_in_the_narration_prompt():
    """The offline provider splits on these two strings to echo the baseline text."""
    assert "DETERMINISTIC BASELINE NARRATIVE:" in prompts.NARRATION_TASK
    assert "\n\nRewrite" in prompts.NARRATION_TASK


def test_every_agent_prompt_shares_the_ground_rules_and_names_its_agent():
    for name, agent in [
        ("RETRIEVAL_SYSTEM_PROMPT", "Retrieval Agent"),
        ("CORRELATION_SYSTEM_PROMPT", "Correlation Agent"),
        ("ANSWER_SYSTEM_PROMPT", "Summarization Agent"),
    ]:
        text = getattr(prompts, name)
        assert agent in text
        assert prompts.GROUND_RULES in text and prompts.RAILWAY_CHECKS in text
    # The two agents whose replies are parsed as JSON are told so; the answer prompt,
    # also used for plain-text chat replies, is not.
    assert prompts.RETRIEVAL_SYSTEM_PROMPT.endswith(prompts.JSON_ONLY)
    assert prompts.CORRELATION_SYSTEM_PROMPT.endswith(prompts.JSON_ONLY)
    assert "JSON" not in prompts.ANSWER_SYSTEM_PROMPT


def test_the_answer_reports_the_human_approval_decision():
    from app.agents.nodes.summarization import _baseline_answer, build_answer_context

    state = {
        "ecr_id": "ECR-1",
        "ecr_input": {"title": "Depart test"},
        "approval": {"required": True, "status": "REJECTED", "decided_by": "qa.lead@enterprise.com"},
    }
    context = build_answer_context(state)
    assert context["human_approval"]["status"] == "REJECTED"
    assert "rejected this analysis, so the test recommendation is on hold" in _baseline_answer(context)
    assert build_answer_context({"ecr_id": "ECR-2"})["human_approval"] == {"requested": False}
