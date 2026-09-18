"""Fraud Screening Service (CMP-014)."""
from schema.transaction_schema import recent_transaction_count

THRESHOLD = 0.82


def score_transaction(request, base_amount):
    velocity = recent_transaction_count(request.get("customer_id"))
    return min(1.0, base_amount / 25000 + velocity * 0.05)


def screen_transaction(request, base_amount, base_currency):
    score = score_transaction(request, base_amount)
    return "HOLD" if score >= THRESHOLD else "ALLOW"
