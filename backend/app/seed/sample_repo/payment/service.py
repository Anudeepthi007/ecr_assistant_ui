"""Payment Service (CMP-003): authorise, capture and settle payments."""
from payment.currency import convert
from payment.validator import ValidationError, validate_payment_request
from fraud.service import screen_transaction
from ledger.service import post_capture
from schema.transaction_schema import insert_transaction


def authorise_payment(request, merchant_config):
    errors = validate_payment_request(request, merchant_config)
    if errors:
        raise ValidationError(errors)
    settlement_currency = merchant_config["settlement_currency"]
    settlement_amount = convert(request["amount"], request["currency"], settlement_currency)
    decision = screen_transaction(request, settlement_amount, settlement_currency)
    if decision == "HOLD":
        return {"status": "PENDING_REVIEW"}
    transaction = insert_transaction(
        amount=request["amount"],
        currency=request["currency"],
        settlement_amount=settlement_amount,
        settlement_currency=settlement_currency,
        idempotency_key=request.get("idempotency_key"),
    )
    return {"status": "AUTHORISED", "transaction_id": transaction["id"]}


def capture_payment(transaction_id, amount):
    post_capture(transaction_id, amount)
    return {"status": "CAPTURED", "transaction_id": transaction_id}
