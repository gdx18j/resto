import uuid

from django.conf import settings
from django.urls import reverse

from .models import Payment

try:
    from yookassa import Configuration, Payment as YooKassaPayment

    YOOKASSA_AVAILABLE = True
except ImportError:
    YOOKASSA_AVAILABLE = False


def _configure():
    if not YOOKASSA_AVAILABLE:
        raise RuntimeError("Install the yookassa package before creating real payments.")
    if not settings.YOOKASSA_SHOP_ID or not settings.YOOKASSA_SECRET_KEY:
        raise RuntimeError("YOOKASSA_SHOP_ID and YOOKASSA_SECRET_KEY are required.")

    Configuration.account_id = settings.YOOKASSA_SHOP_ID
    Configuration.secret_key = settings.YOOKASSA_SECRET_KEY


def _payment_record(order):
    payment = (
        order.payments.filter(method=Payment.Method.ONLINE)
        .order_by("-created_at")
        .first()
    )

    if payment:
        return payment

    return Payment.objects.create(
        order=order,
        method=Payment.Method.ONLINE,
        amount=order.total_amount,
        currency=order.currency,
    )


def create_payment(order, return_url):
    if settings.YOOKASSA_MOCK:
        return create_mock_payment(order)

    _configure()

    table_label = order.table.number if order.table else "-"
    remote_payment = YooKassaPayment.create(
        {
            "amount": {
                "value": f"{order.total_amount:.2f}",
                "currency": order.currency,
            },
            "confirmation": {
                "type": "redirect",
                "return_url": return_url,
            },
            "capture": True,
            "description": f"Order #{order.id}, table {table_label}",
            "metadata": {
                "order_id": str(order.id),
            },
        },
        str(uuid.uuid4()),
    )

    payment = _payment_record(order)
    payment.provider = "yookassa"
    payment.external_id = remote_payment.id
    payment.status = Payment.Status.PENDING
    payment.save(update_fields=["provider", "external_id", "status"])

    return remote_payment.confirmation.confirmation_url


def fetch_payment(payment_id):
    _configure()
    return YooKassaPayment.find_one(payment_id)


def create_mock_payment(order):
    payment = _payment_record(order)
    payment.provider = "mock"
    payment.external_id = f"mock_{uuid.uuid4().hex[:16]}"
    payment.status = Payment.Status.PENDING
    payment.save(update_fields=["provider", "external_id", "status"])

    return reverse("orders:mock_pay", args=[order.id])
