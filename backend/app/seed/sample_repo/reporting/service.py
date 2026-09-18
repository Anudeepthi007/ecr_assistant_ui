"""Reporting Service (CMP-013): reconciliation extracts."""
from schema.transaction_schema import settled_transactions
from ledger.service import balance


def reconciliation_report(currency=None):
    rows = settled_transactions(currency)
    settled = sum(row["settlement_amount"] or 0 for row in rows)
    return {
        "currency": currency or "ALL",
        "transaction_count": len(rows),
        "settled_amount": settled,
        "ledger_balance": balance(),
    }
