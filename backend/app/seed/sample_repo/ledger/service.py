"""Ledger Service (CMP-015): double-entry postings."""
from schema.transaction_schema import find_transaction

_POSTINGS = []


def post_capture(transaction_id, amount):
    transaction = find_transaction(transaction_id)
    _POSTINGS.append({"tx": transaction_id, "debit": amount, "credit": amount})
    return transaction


def post_refund(transaction_id, amount, original_rate):
    _POSTINGS.append({"tx": transaction_id, "debit": -amount, "credit": -amount, "rate": original_rate})
    return True


def balance():
    return sum(p["debit"] - p["credit"] for p in _POSTINGS)
