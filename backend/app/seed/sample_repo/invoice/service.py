"""Invoice Service (CMP-012)."""
from payment.currency import minor_units
from schema.transaction_schema import find_transaction

_SEQUENCE = {"EU": 0}


def next_invoice_number(entity="EU"):
    _SEQUENCE[entity] += 1
    return entity + "-INV-" + str(_SEQUENCE[entity]).zfill(6)


def create_invoice(transaction_id, amount, currency):
    find_transaction(transaction_id)
    return {
        "invoice_number": next_invoice_number(),
        "amount": round(amount, minor_units(currency)),
        "currency": currency,
    }
