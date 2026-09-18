"""Notification Service (CMP-011)."""
from notification.templates import ORDER_CONFIRMATION, REFUND_CONFIRMATION, render

_SENT = []


def send_order_confirmation(customer_id, invoice_number):
    body = render(ORDER_CONFIRMATION, {"order_id": invoice_number})
    _SENT.append({"to": customer_id, "body": body})
    return True


def send_refund_confirmation(transaction_id):
    body = render(REFUND_CONFIRMATION, {"transaction_id": transaction_id})
    _SENT.append({"to": transaction_id, "body": body})
    return True
