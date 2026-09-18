"""Retrieval Agent step: understand and classify the ECR.

Deterministic classification, so the change type and complexity are
reproducible and testable. The Retrieval Agent's LLM reasoning runs right after
this, in :mod:`retrieval_planning`; numeric fields are never taken from the model.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any

from app.agents.tools.registry import tool
from app.database import session_scope
from app.llm.base import tokenize
from app.models import Component, Requirement
from app.schemas.common import ChangeType
from app.schemas.ecr import ECRUnderstanding
from app.services.code_analysis_service import KEYWORD_COMPONENT_MAP

CHANGE_TYPE_SIGNALS: dict[str, list[str]] = {
    ChangeType.UI.value: [
        "button", "label", "page", "screen", "css", "layout", "wording", "text",
        "portal", "frontend", "ux", "tooltip", "banner", "template",
    ],
    ChangeType.API.value: [
        "api", "endpoint", "contract", "rest", "payload", "route", "version",
        "request", "response", "schema v2", "openapi",
    ],
    ChangeType.BACKEND.value: [
        "logic", "service", "calculation", "processing", "algorithm", "handler",
        "validation", "rounding", "orchestration", "workflow",
    ],
    ChangeType.DATABASE.value: [
        "database", "schema", "column", "table", "migration", "index", "backfill",
        "sql", "query", "partition", "constraint",
    ],
    ChangeType.SECURITY.value: [
        "authentication", "authorisation", "authorization", "mfa", "token",
        "credential", "encryption", "security", "session", "step-up", "oauth",
    ],
    ChangeType.INFRASTRUCTURE.value: [
        "infrastructure", "redis", "cache", "kubernetes", "deployment", "scaling",
        "cluster", "pipeline", "terraform", "network",
    ],
    ChangeType.CONFIGURATION.value: [
        "configuration", "config", "feature flag", "toggle", "threshold",
        "parameter", "setting", "property",
    ],
    ChangeType.INTEGRATION.value: [
        "integration", "third-party", "third party", "vendor", "webhook",
        "external", "partner", "connector", "anti-corruption",
    ],
}

RISK_INDICATOR_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("financial_transaction", ("payment", "transaction", "refund", "settlement", "ledger", "invoice", "currency")),
    ("validation_logic_change", ("validation", "validator", "validate", "reject", "rule")),
    ("schema_migration", ("schema", "migration", "column", "backfill", "index")),
    ("authentication_change", ("authentication", "mfa", "login", "sign-in", "step-up")),
    ("authorization_change", ("authorisation", "authorization", "permission", "role", "token")),
    ("shared_library_change", ("shared", "library", "common", "validator", "helper")),
    ("third_party_integration", ("third-party", "third party", "vendor", "external", "partner")),
    ("concurrency_change", ("concurrent", "lock", "race", "idempotency", "parallel")),
    ("data_migration", ("backfill", "migrate", "historical rows", "data migration")),
    ("customer_facing", ("customer", "portal", "page", "email", "notification")),
    ("performance_change", ("performance", "latency", "cache", "optimise", "optimize", "index")),
]

FILE_EXTENSION_SIGNALS = {
    ".sql": ChangeType.DATABASE.value,
    ".tf": ChangeType.INFRASTRUCTURE.value,
    ".yaml": ChangeType.CONFIGURATION.value,
    ".yml": ChangeType.CONFIGURATION.value,
    ".json": ChangeType.CONFIGURATION.value,
    ".tsx": ChangeType.UI.value,
    ".jsx": ChangeType.UI.value,
    ".css": ChangeType.UI.value,
}


@tool("classify_change", "Score the change against every change-type signal vocabulary.")
def classify_change(text: str, changed_files: list[str]) -> dict[str, float]:
    lowered = text.lower()
    scores: dict[str, float] = {}
    for change_type, signals in CHANGE_TYPE_SIGNALS.items():
        hits = sum(1 for signal in signals if signal in lowered)
        scores[change_type] = float(hits)
    for path in changed_files:
        lower_path = path.lower()
        for extension, change_type in FILE_EXTENSION_SIGNALS.items():
            if lower_path.endswith(extension):
                scores[change_type] = scores.get(change_type, 0.0) + 1.5
        if "schema" in lower_path or "migration" in lower_path:
            scores[ChangeType.DATABASE.value] += 2.0
        if "portal" in lower_path or "page" in lower_path:
            scores[ChangeType.UI.value] += 2.0
        if "router" in lower_path or "gateway" in lower_path or "api" in lower_path:
            scores[ChangeType.API.value] += 1.5
        if "service.py" in lower_path or "validator" in lower_path:
            scores[ChangeType.BACKEND.value] += 1.5
        if "auth" in lower_path:
            scores[ChangeType.SECURITY.value] += 1.5
        if "infra" in lower_path:
            scores[ChangeType.INFRASTRUCTURE.value] += 1.5
    total = sum(scores.values()) or 1.0
    return {key: round(value / total, 3) for key, value in scores.items() if value}


@tool("extract_entities", "Extract features, keywords, domains and candidate components.")
def extract_entities(
    text: str, changed_files: list[str], linked_requirements: list[str] | None = None
) -> dict[str, Any]:
    lowered = text.lower()
    with session_scope() as db:
        known_features: set[str] = set()
        domain_by_feature: dict[str, str] = {}
        requirement_domain: dict[str, str] = {}
        for requirement in db.query(Requirement).all():
            requirement_domain[requirement.requirement_id] = requirement.domain
            for feature in requirement.features or []:
                known_features.add(feature)
                domain_by_feature[feature.lower()] = requirement.business_domain
        components = db.query(Component).all()
        component_names = {c.name.lower(): c.component_id for c in components}
        component_domain = {c.component_id: c.domain for c in components}

    features = sorted({f for f in known_features if f.lower() in lowered})
    if not features:
        # fall back to partial token overlap with the feature catalogue
        text_tokens = set(tokenize(text))
        for feature in known_features:
            feature_tokens = set(tokenize(feature))
            if feature_tokens and len(feature_tokens & text_tokens) >= max(1, len(feature_tokens) - 1):
                features.append(feature)
        features = sorted(set(features))

    counts = Counter(tokenize(text))
    keywords = [word for word, _ in counts.most_common(24) if len(word) > 3][:12]
    for path in changed_files:
        stem = re.split(r"[/\\.]", path)
        keywords.extend(part for part in stem if len(part) > 3 and part not in keywords)

    candidates: set[str] = set()
    for keyword, component_id in KEYWORD_COMPONENT_MAP.items():
        # Match at the start of a word only: "orders" and "reporting" count, but
        # "recorder", "reorder" and "require" must not hit "order", "order", "ui".
        if re.search(rf"\b{re.escape(keyword)}", lowered):
            candidates.add(component_id)
    named: set[str] = set()
    for name, component_id in component_names.items():
        if name in lowered:
            named.add(component_id)
    candidates |= named

    # Keep candidates inside the ECR's own product domain. The requirements the ECR
    # is linked to are the strongest evidence of that domain, then the components it
    # names. Without this, commerce keywords ("validation", "report") in a rail
    # change pull payment services into its impact and its test suite.
    domain_votes = Counter(
        requirement_domain[r] for r in (linked_requirements or []) if r in requirement_domain
    ) or Counter(component_domain[c] for c in named if c in component_domain)
    product_domain = domain_votes.most_common(1)[0][0] if domain_votes else None
    if product_domain:
        candidates = {c for c in candidates if component_domain.get(c) == product_domain}

    domains = [domain_by_feature.get(f.lower()) for f in features]
    domains = [d for d in domains if d]
    business_domain = Counter(domains).most_common(1)[0][0] if domains else "General"

    indicators = [
        indicator
        for indicator, signals in RISK_INDICATOR_RULES
        if any(signal in lowered for signal in signals)
    ]
    return {
        "affected_features": features[:8],
        "technical_keywords": keywords[:12],
        "candidate_components": sorted(candidates),
        "business_domain": business_domain,
        "product_domain": product_domain,
        "risk_indicators": indicators,
    }


def _complexity(scores: dict[str, float], entities: dict[str, Any], changed_files: list[str], text: str) -> float:
    distinct_types = len([v for v in scores.values() if v >= 0.15])
    value = (
        0.3 * min(1.0, distinct_types / 3.0)
        + 0.25 * min(1.0, len(entities["risk_indicators"]) / 4.0)
        + 0.2 * min(1.0, len(changed_files) / 5.0)
        + 0.15 * min(1.0, len(entities["candidate_components"]) / 4.0)
        + 0.1 * min(1.0, len(text.split()) / 120.0)
    )
    return round(min(1.0, value), 3)


def ecr_understanding_step(state: dict[str, Any]) -> dict[str, Any]:
    ecr = state["ecr_input"]
    changed_files = list(ecr.get("changed_files") or [])
    text = " ".join(
        part
        for part in (
            f"{ecr.get('title', '')}. {ecr.get('description', '')}",
            ecr.get("steps_to_reproduce") or "",
            ecr.get("observed_behavior") or "",
            ecr.get("expected_behavior") or "",
        )
        if part
    )

    scores = classify_change(text, changed_files)
    entities = extract_entities(text, changed_files, list(ecr.get("linked_requirements") or []))
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    if not ranked:
        change_type = ChangeType.MIXED.value
    else:
        top, top_score = ranked[0]
        runner_up, runner_score = ranked[1] if len(ranked) > 1 else (None, 0.0)
        if runner_up and abs(top_score - runner_score) < 0.08:
            pair = {top, runner_up}
            if pair == {ChangeType.API.value, ChangeType.BACKEND.value}:
                change_type = ChangeType.API_AND_BACKEND.value
            else:
                change_type = ChangeType.MIXED.value
        else:
            change_type = top

    complexity = _complexity(scores, entities, changed_files, text)
    confidence = round(
        min(0.97, 0.6 + 0.12 * bool(entities["affected_features"]) + 0.12 * bool(changed_files)
            + 0.08 * bool(entities["candidate_components"]) + 0.05 * bool(scores)),
        3,
    )
    baseline_summary = (
        f"{ecr.get('ecr_id')} is a {change_type.replace('_', ' ').lower()} in the "
        f"{entities['business_domain']} domain affecting "
        f"{', '.join(entities['affected_features']) or 'unmapped functionality'}. "
        f"{len(changed_files)} file(s) are declared on the change and "
        f"{len(entities['candidate_components'])} candidate component(s) were identified."
    )

    fallback = {
        "ecr_id": ecr.get("ecr_id", ""),
        "change_type": change_type,
        "change_type_scores": scores,
        "business_domain": entities["business_domain"],
        "affected_features": entities["affected_features"],
        "technical_keywords": entities["technical_keywords"],
        "candidate_components": entities["candidate_components"],
        "risk_indicators": entities["risk_indicators"],
        "change_complexity": complexity,
        "summary": baseline_summary,
        "confidence": confidence,
    }

    understanding = ECRUnderstanding.model_validate(fallback)

    reasoning = (
        f"Classified as {understanding.change_type.value} "
        f"(confidence {understanding.confidence:.0%}) from {len(scores)} signal groups. "
        f"Extracted {len(understanding.technical_keywords)} technical keywords, "
        f"{len(understanding.affected_features)} affected feature(s) and "
        f"{len(understanding.risk_indicators)} risk indicator(s)."
    )
    return {
        "ecr_analysis": understanding.model_dump(mode="json"),
        "tools_used": {"ecr_understanding": ["classify_change", "extract_entities"]},
        "_confidence": understanding.confidence,
        "_reasoning": reasoning,
        "_summary": {
            "change_type": understanding.change_type.value,
            "business_domain": understanding.business_domain,
            "affected_features": understanding.affected_features,
            "risk_indicators": understanding.risk_indicators,
        },
    }
