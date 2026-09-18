"""Currency Service (CMP-005): FX rate sourcing and catalogue."""
from infra.redis_cache import cache_get, cache_set

RATE_TTL_SECONDS = 900
_CATALOGUE = ["EUR", "USD", "GBP", "JPY", "CHF", "SEK", "BHD"]


def supported_currencies():
    return list(_CATALOGUE)


def refresh_rates():
    """Pull the treasury feed and refresh the cache."""
    rates = {"EUR:USD": 1.09, "USD:EUR": 0.92, "EUR:GBP": 0.85, "EUR:JPY": 158.4}
    cache_set("fx_rates", rates, RATE_TTL_SECONDS)
    return rates


def get_rate(from_currency, to_currency):
    rates = cache_get("fx_rates") or refresh_rates()
    key = from_currency + ":" + to_currency
    if key not in rates:
        raise KeyError("NO_RATE_AVAILABLE")
    return rates[key]
