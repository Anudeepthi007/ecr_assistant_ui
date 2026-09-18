"""Refund Service (CMP-007): full and partial refunds."""
from payment.validator import validate_payment_request
from ledger.service import post_refund
from schema.transaction_schema import find_transaction
from notification.service import send_refund_confirmation


def refundable_amount(transaction_id, already_refunded):
    transaction = find_transaction(transaction_id)
    return (transaction["amount"] if transaction else 0) - already_refunded


def process_refund(request, merchant_config, already_refunded=0):
    errors = validate_payment_request(request, merchant_config)
    if errors:
        return {"status": "REJECTED", "errors": errors}
    remaining = refundable_amount(request["transaction_id"], already_refunded)
    if request["amount"] > remaining:
        return {"status": "REJECTED", "errors": ["AMOUNT_EXCEEDS_REFUNDABLE"]}
    post_refund(request["transaction_id"], request["amount"], request.get("original_rate"))
    send_refund_confirmation(request["transaction_id"])
    return {"status": "REFUNDED"}
