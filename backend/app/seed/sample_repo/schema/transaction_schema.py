"""Transaction Database access layer and schema (CMP-008)."""
TRANSACTION_COLUMNS = [
    "id",
    "amount",
    "currency",
    "settlement_amount",
    "settlement_currency",
    "status",
    "idempotency_key",
    "created_at",
    "settled_at",
]

_ROWS = []


def insert_transaction(amount, currency, settlement_amount, settlement_currency, idempotency_key):
    row = {
        "id": "TX-" + str(len(_ROWS) + 1),
        "amount": amount,
        "currency": currency,
        "settlement_amount": settlement_amount,
        "settlement_currency": settlement_currency,
        "status": "AUTHORISED",
        "idempotency_key": idempotency_key,
    }
    _ROWS.append(row)
    return row


def find_transaction(transaction_id):
    for row in _ROWS:
        if row["id"] == transaction_id:
            return row
    return None


def recent_transaction_count(customer_id):
    return len([row for row in _ROWS if row.get("customer_id") == customer_id])


def settled_transactions(currency=None):
    return [r for r in _ROWS if currency is None or r["currency"] == currency]
