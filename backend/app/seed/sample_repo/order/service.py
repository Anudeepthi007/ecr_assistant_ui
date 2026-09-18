"""Order Service (CMP-006): cart, checkout and totals."""
from payment.service import authorise_payment
from invoice.service import create_invoice
from notification.service import send_order_confirmation
from payment.currency import minor_units


def calculate_total(line_items, tax_rate, discount, currency):
    subtotal = sum(item["price"] * item["quantity"] for item in line_items)
    discounted = subtotal - discount
    total = discounted * (1 + tax_rate)
    return round(total, minor_units(currency))


def checkout(cart, merchant_config):
    total = calculate_total(cart["items"], cart["tax_rate"], cart.get("discount", 0), cart["currency"])
    result = authorise_payment(
        {
            "amount": total,
            "currency": cart["currency"],
            "instrument_token": cart["instrument_token"],
            "idempotency_key": cart["idempotency_key"],
        },
        merchant_config,
    )
    if result["status"] != "AUTHORISED":
        return {"status": "CHECKOUT_FAILED", "payment": result}
    invoice = create_invoice(result["transaction_id"], total, cart["currency"])
    send_order_confirmation(cart["customer_id"], invoice["invoice_number"])
    return {"status": "CONFIRMED", "invoice": invoice}


def cancel_order(order_id, captured):
    return {"status": "REFUND_REQUESTED" if captured else "VOIDED", "order_id": order_id}
