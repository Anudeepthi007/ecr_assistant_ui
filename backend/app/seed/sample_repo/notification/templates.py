"""Notification templates (CMP-011). Content-only module."""
ORDER_CONFIRMATION = {
    "subject": "Your order {{order_id}} is confirmed",
    "header": "Thanks for your order",
    "footer": "Enterprise Commerce, 1 Market Street",
}

REFUND_CONFIRMATION = {
    "subject": "Your refund for {{transaction_id}} is on its way",
    "header": "Refund processed",
    "footer": "Enterprise Commerce, 1 Market Street",
}

SECURITY_ALERT = {
    "subject": "Security check on your account",
    "header": "We need to verify it is you",
    "footer": "Enterprise Commerce Security",
}


def render(template, values):
    body = template["header"]
    for key, value in values.items():
        body = body.replace("{{" + key + "}}", str(value))
    return body
