"""Shared cache adapter (infrastructure)."""
_STORE = {}


def cache_get(key):
    entry = _STORE.get(key)
    return entry["value"] if entry else None


def cache_set(key, value, ttl_seconds):
    _STORE[key] = {"value": value, "ttl": ttl_seconds}
    return True
