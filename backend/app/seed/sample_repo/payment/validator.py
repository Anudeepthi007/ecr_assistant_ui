"""Shared payment/refund validation library (Payment Validator, CMP-004)."""
from payment.currency import is_supported_currency, minor_units

MAX_AMOUNT_DEFAULT = 10000


class ValidationError(Exception):
    """Raised when a payment request cannot be processed."""


def validate_amount(amount, currency, merchant_config):
    """Amount must be positive and within the merchant ceiling."""
    errors = []
    if amount is None or amount <= 0:
        errors.append("INVALID_AMOUNT")
    ceiling = merchant_config.get("max_amount", MAX_AMOUNT_DEFAULT)
    if amount is not None and amount > ceiling:
        errors.append("AMOUNT_ABOVE_CEILING")
    if amount is not None and round(amount, minor_units(currency)) != amount:
        errors.append("INVALID_MINOR_UNITS")
    return errors


def validate_currency(currency, merchant_config):
    """Reject any currency outside the merchant supported list."""
    errors = []
    if not currency or len(currency) != 3:
        errors.append("MALFORMED_CURRENCY")
        return errors
    if not is_supported_currency(currency):
        errors.append("UNSUPPORTED_CURRENCY")
    if currency not in merchant_config.get("supported_currencies", []):
        errors.append("UNSUPPORTED_CURRENCY")
    return errors


def validate_payment_request(request, merchant_config):
    """Entry point used by both the payment and the refund service."""
    errors = []
    errors += validate_amount(request.get("amount"), request.get("currency"), merchant_config)
    errors += validate_currency(request.get("currency"), merchant_config)
    if not request.get("instrument_token"):
        errors.append("MISSING_INSTRUMENT")
    return sorted(set(errors))
