"""Overall confidence of a run."""
from __future__ import annotations

from app.services.confidence import compute_confidence


def test_confidence_penalises_failures():
    clean, penalties = compute_confidence({"a": 0.9, "b": 0.9, "c": 0.9, "d": 0.9, "e": 0.9})
    degraded, degraded_penalties = compute_confidence(
        {"a": 0.9, "b": 0.9, "c": 0.9, "d": 0.9, "e": 0.9}, errors=[{"agent": "Retrieval Agent"}]
    )
    assert clean > degraded
    assert not penalties
    assert degraded_penalties


def test_confidence_stays_in_range():
    low, _ = compute_confidence({}, errors=[{"agent": "x"}] * 20)
    assert 0.05 <= low <= 1.0
