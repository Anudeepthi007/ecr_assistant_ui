"""User Service (CMP-009): profile and address book."""
from auth.service import revoke_sessions

_PROFILES = {}


def get_profile(user_id):
    return _PROFILES.setdefault(user_id, {"display_name": "", "addresses": []})


def update_profile(user_id, changes):
    profile = get_profile(user_id)
    profile.update(changes)
    return profile


def upsert_address(user_id, address):
    """Partial update must preserve the default flag (see BUG-244)."""
    profile = get_profile(user_id)
    for existing in profile["addresses"]:
        if existing["id"] == address["id"]:
            existing.update({k: v for k, v in address.items() if v is not None})
            return existing
    profile["addresses"].append(address)
    return address


def change_password(user_id, new_password):
    revoke_sessions(user_id)
    return True
