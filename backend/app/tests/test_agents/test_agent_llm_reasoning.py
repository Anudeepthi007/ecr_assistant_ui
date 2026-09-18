"""Each of the three agents reasons with the LLM, and what it says stays grounded."""
from __future__ import annotations

from app.agents.nodes import correlation_review, retrieval_planning
from app.agents.nodes.planning import build_plan
from app.agents.orchestrator import run_workflow
from app.database import session_scope
from app.llm import openai_provider
from app.llm import provider as provider_module
from app.llm.base import BaseLLMProvider
from app.llm.provider import get_llm
from app.repositories import ECRRepository
from app.schemas.common import ChangeType


class FakeLLM:
    """A real (non-mock) provider as far as the agents can tell."""

    is_mock = False

    def __init__(self, replies: dict | None = None) -> None:
        self.replies = replies or {}
        self.calls: list[str] = []

    def generate(self, prompt, *, fallback=None, **_kwargs):
        self.calls.append("generate")
        return "Grounded answer from the model."

    def generate_structured(self, prompt, schema, *, fallback=None, **_kwargs):
        self.calls.append(schema.__name__)
        data = {**(fallback or {}), "source": "llm", **self.replies.get(schema.__name__, {})}
        return schema.model_validate(data)


ECR_STATE = {
    "ecr_input": {"ecr_id": "ECR-T", "title": "Tune braking", "description": "Adjust the curve."},
    "ecr_analysis": {"summary": "Rule summary.", "technical_keywords": ["braking"]},
}


def _bundle_state() -> dict:
    return {
        "ecr_id": "ECR-T",
        "requirements": [{"requirement_id": "REQ-1", "title": "Brake enforcement"}],
        "comments": [
            {"comment_id": "CMT-1", "author": "Ana", "sentiment": "CONCERN", "target_id": "REQ-1", "references": []}
        ],
        "evidence": [{"evidence_id": "EV-1", "title": "HIL run", "outcome": "PASS", "target_id": "REQ-1"}],
        "collaboration_analysis": {"evidence_gaps": []},
    }


def test_retrieval_agent_llm_plans_the_search(monkeypatch):
    fake = FakeLLM(
        {
            "RetrievalPlan": {
                "summary": "Changes the braking curve.",
                "search_terms": ["Braking curve", "braking curve", "REQ-101", "ab", "penalty brake"],
                "could_break": ["enforcement timing"],
                "needs_dependency_check": True,
                "dependency_reason": "The braking model is shared.",
            }
        }
    )
    monkeypatch.setattr(retrieval_planning, "get_llm", lambda: fake)

    out = retrieval_planning.retrieval_planning_step(ECR_STATE)
    plan = out["retrieval_plan"]

    assert fake.calls == ["RetrievalPlan"]
    assert plan["source"] == "llm"
    assert plan["search_terms"] == ["braking curve", "penalty brake"]  # no duplicates, ids or noise
    assert out["ecr_analysis"]["summary"] == "Changes the braking curve."
    assert "penalty brake" in retrieval_planning.search_query({**ECR_STATE, "retrieval_plan": plan})
    # The LLM can add the dependency walk the rules would skip for a UI change.
    ui = build_plan({"change_type": ChangeType.UI.value, "risk_indicators": []}, {}, plan)
    assert "dependencies" in ui["investigations"]
    assert "Retrieval Agent" in ui["reasons"]["dependencies"]


def test_without_an_llm_retrieval_uses_the_rule_keywords():
    out = retrieval_planning.retrieval_planning_step(ECR_STATE)
    assert out["retrieval_plan"]["source"] == "rules"
    assert retrieval_planning.search_query({**ECR_STATE, **out}) == "Tune braking. Adjust the curve."


def test_correlation_agent_llm_findings_must_cite_real_artefacts(monkeypatch):
    fake = FakeLLM(
        {
            "CorrelationReview": {
                "summary": "One contradiction.",
                "conflicts": [
                    {"ids": ["CMT-1", "EV-1", "BUG-999"], "text": "Concern against a pass."},
                    {"ids": ["BUG-999"], "text": "Invented."},
                ],
                "key_links": [],
                "gaps": [],
            }
        }
    )
    monkeypatch.setattr(correlation_review, "get_llm", lambda: fake)

    review = correlation_review.correlation_review_step(_bundle_state())["correlation_review"]

    assert fake.calls == ["CorrelationReview"]
    assert review["source"] == "llm"
    assert review["conflicts"] == [{"ids": ["CMT-1", "EV-1"], "text": "Concern against a pass."}]


def test_rule_review_spots_a_concern_contradicted_by_a_pass():
    review = correlation_review.correlation_review_step(_bundle_state())["correlation_review"]
    assert review["source"] == "rules"
    assert review["conflicts"][0]["ids"] == ["CMT-1", "REQ-1", "EV-1"]


class CountingProvider(BaseLLMProvider):
    """A remote provider that records every request instead of sending it."""

    name = "counting"
    is_mock = False
    supports_remote_embeddings = False

    def __init__(self) -> None:
        self.requests: list[str] = []

    def generate(self, prompt, *, system=None, max_tokens=None, temperature=0.2, fast=False):
        self.requests.append("generate")
        return "Model text."

    def generate_structured(self, prompt, schema, *, system=None, fallback=None, temperature=0.0, fast=True):
        self.requests.append(schema.__name__)
        data = {**(fallback or {}), "source": "llm"}
        if schema.__name__ == "SummaryReply":
            data.update(answer="Grounded answer from the model.", defect_summary="Model defect summary.")
        return schema.model_validate(data)

    def embed(self, texts):
        self.requests.append("embed")
        return super().embed(texts)


def test_an_analysis_makes_exactly_three_llm_requests_one_per_agent(rag, monkeypatch):
    """Guardrail: the gateway quota pays for one request per agent and nothing else."""
    counting = CountingProvider()
    monkeypatch.setattr(provider_module, "build_provider", lambda name=None: counting)
    get_llm.cache_clear()
    try:
        with session_scope() as db:
            ecr = ECRRepository(db).get("ECR-2026-001").as_dict()
        _, state = run_workflow(ecr, {})
    finally:
        get_llm.cache_clear()

    assert sorted(counting.requests) == ["CorrelationReview", "RetrievalPlan", "SummaryReply"]
    assert state["retrieval_plan"]["source"] == "llm"
    assert state["correlation_review"]["summary"]
    assert state["final_answer"] == "Grounded answer from the model."
    assert state["defect_summary"] == "Model defect summary."
    report = state["final_report"]
    assert report["retrieval_plan"]["source"] == "llm"
    assert "correlation_findings" in {section["key"] for section in report["sections"]}


def test_search_embeddings_stay_local_by_default(monkeypatch):
    monkeypatch.setattr(openai_provider.settings, "openai_api_key", "test-key")
    assert openai_provider.OpenAIProvider().supports_remote_embeddings is False
