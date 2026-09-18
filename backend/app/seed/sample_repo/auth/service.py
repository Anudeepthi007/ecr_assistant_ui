"""Auth Service (CMP-010): sessions, MFA and step-up assertions."""
from notification.service import send_refund_confirmation

ACCESS_TOKEN_TTL = 1800
HIGH_VALUE_THRESHOLD = 5000
_REVOKED = set()


def issue_token(user_id, device_trusted):
    return {"sub": user_id, "device_trusted": device_trusted, "ttl": ACCESS_TOKEN_TTL}


def refresh_token(token):
    """Device trust must survive a refresh (see BUG-228)."""
    return {"sub": token["sub"], "device_trusted": token.get("device_trusted", False), "ttl": ACCESS_TOKEN_TTL}


def revoke_sessions(user_id):
    _REVOKED.add(user_id)
    return True


def requires_step_up(amount, token):
    return amount >= HIGH_VALUE_THRESHOLD or not token.get("device_trusted")


def validate_step_up_assertion(assertion, token):
    return bool(assertion) and assertion.get("sub") == token.get("sub")
