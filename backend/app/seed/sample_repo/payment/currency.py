"""Currency helpers used inside the payment boundary (CMP-005)."""
from currency.service import get_rate, supported_currencies

ZERO_DECIMAL = {"JPY", "KRW", "VND"}
THREE_DECIMAL = {"BHD", "KWD", "OMR"}


def minor_units(currency):
    if currency in ZERO_DECIMAL:
        return 0
    if currency in THREE_DECIMAL:
        return 3
    return 2


def is_supported_currency(currency):
    return currency in supported_currencies()


def convert(amount, from_currency, to_currency):
    """Convert using the rate effective now; raises for unknown currencies."""
    if from_currency == to_currency:
        return amount
    rate = get_rate(from_currency, to_currency)
    return round(amount * rate, minor_units(to_currency))
