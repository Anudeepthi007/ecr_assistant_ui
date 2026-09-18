"""API Gateway routing table (CMP-002)."""
from auth.service import refresh_token
from payment.service import authorise_payment
from order.service import checkout
from refund.service import process_refund

ROUTES = {
    "POST /payments": "payment.service.authorise_payment",
    "POST /orders/checkout": "order.service.checkout",
    "POST /refunds": "refund.service.process_refund",
    "POST /refunds/v2": "refund.service.process_refund",
    "POST /auth/refresh": "auth.service.refresh_token",
}


def dispatch(route, payload, merchant_config):
    if route == "POST /payments":
        return authorise_payment(payload, merchant_config)
    if route == "POST /orders/checkout":
        return checkout(payload, merchant_config)
    if route.startswith("POST /refunds"):
        return process_refund(payload, merchant_config)
    if route == "POST /auth/refresh":
        return refresh_token(payload)
    raise KeyError("NO_ROUTE")
